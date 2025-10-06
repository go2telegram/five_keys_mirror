from __future__ import annotations

import asyncio
import json
import math
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import httpx

from app.config import settings


@dataclass
class SearchResult:
    """Single search hit."""

    title: str
    snippet: str
    score: float
    source: str
    path: str


class BaseEmbedder:
    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError


class OpenAIEmbedder(BaseEmbedder):
    """Embedding backend that talks to OpenAI-compatible APIs."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": list(texts),
        }
        async with httpx.AsyncClient(timeout=60.0, base_url=self.base_url) as client:
            resp = await client.post("/embeddings", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            vectors: List[List[float]] = []
            for item in data.get("data", []):
                vectors.append([float(x) for x in item.get("embedding", [])])
            return vectors


class LocalEmbedder(BaseEmbedder):
    """Deterministic local hash-embedding backend (fallback)."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension
        self._token_pattern = re.compile(r"[\wа-яё]+", re.IGNORECASE)

    def _tokenize(self, text: str) -> Iterable[str]:
        return (token.lower() for token in self._token_pattern.findall(text))

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dimension
        tokens = list(self._tokenize(text))
        if not tokens:
            return vec
        for token in tokens:
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]


class SemanticSearchService:
    def __init__(self, root_dir: Path, embedder: Optional[BaseEmbedder] = None) -> None:
        self.root_dir = root_dir
        self.docs_dir = root_dir / "docs"
        self.kb_path = root_dir / "knowledge" / "base.json"
        self.index_path = root_dir / "knowledge" / "index.json"
        self.embedder = embedder or self._detect_embedder()
        self._entries: List[Dict] | None = None
        self._meta: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _detect_embedder(self) -> BaseEmbedder:
        if settings.OPENAI_API_KEY:
            return OpenAIEmbedder(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE,
                model=getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            )
        return LocalEmbedder()

    async def ensure_index(self, force: bool = False) -> None:
        async with self._lock:
            current_meta = self._collect_meta()
            if not force:
                if self._entries is not None and not self._meta_differs(current_meta, self._meta):
                    return
                loaded = self._load_cached_index()
                if loaded and not self._meta_differs(current_meta, self._meta):
                    return
            await self._rebuild_index(current_meta)

    async def search(self, query: str, limit: Optional[int] = None) -> List[SearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        top_k = limit or settings.SEMANTIC_SEARCH_TOP_K
        await self.ensure_index()
        if not self._entries:
            return []
        query_vec = (await self.embedder.embed([query]))[0]
        scored: List[tuple[float, Dict]] = []
        for entry in self._entries:
            embedding = entry.get("embedding", [])
            score = self._cosine_similarity(query_vec, embedding)
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        results: List[SearchResult] = []
        for score, entry in scored[:top_k]:
            snippet = self._format_snippet(entry.get("text", ""))
            results.append(
                SearchResult(
                    title=entry.get("title", "(без названия)"),
                    snippet=snippet,
                    score=score,
                    source=entry.get("source", "unknown"),
                    path=entry.get("path", ""),
                )
            )
        return results

    async def rebuild(self) -> None:
        await self.ensure_index(force=True)

    def _collect_meta(self) -> Dict[str, float]:
        meta: Dict[str, float] = {}
        if self.kb_path.exists():
            meta[str(self.kb_path.relative_to(self.root_dir))] = self.kb_path.stat().st_mtime
        if self.docs_dir.exists():
            for path in sorted(self.docs_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(self.root_dir)
                    meta[str(rel)] = path.stat().st_mtime
        return meta

    def _meta_differs(self, current: Dict[str, float], cached: Dict[str, float]) -> bool:
        if current.keys() != cached.keys():
            return True
        for key, value in current.items():
            cached_value = cached.get(key)
            if cached_value != value:
                return True
        return False

    def _load_cached_index(self) -> bool:
        if not self.index_path.exists():
            return False
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            meta = data.get("meta", {})
            if not isinstance(entries, list) or not isinstance(meta, dict):
                return False
            self._entries = entries
            self._meta = {str(k): float(v) for k, v in meta.items()}
            return True
        except Exception:
            return False

    async def _rebuild_index(self, current_meta: Dict[str, float]) -> None:
        documents = self._gather_documents()
        texts = [doc["text"] for doc in documents]
        embeddings = await self.embedder.embed(texts) if texts else []
        entries: List[Dict] = []
        for doc, embedding in zip(documents, embeddings):
            entries.append({
                "id": doc["id"],
                "title": doc["title"],
                "text": doc["text"],
                "path": doc["path"],
                "source": doc["source"],
                "embedding": [float(x) for x in embedding],
            })
        self._entries = entries
        self._meta = current_meta
        payload = {
            "meta": current_meta,
            "entries": entries,
        }
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _gather_documents(self) -> List[Dict]:
        docs: List[Dict] = []
        if self.kb_path.exists():
            try:
                data = json.loads(self.kb_path.read_text(encoding="utf-8"))
                for item in data:
                    text = (item.get("content") or "").strip()
                    if not text:
                        continue
                    title = (item.get("title") or item.get("id") or "Запись базы знаний").strip()
                    docs.append({
                        "id": f"kb::{item.get('id', title)}",
                        "title": title,
                        "text": text,
                        "path": str(self.kb_path.relative_to(self.root_dir)),
                        "source": "knowledge",
                    })
            except Exception:
                pass
        if self.docs_dir.exists():
            for path in sorted(self.docs_dir.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".md", ".txt"}:
                    continue
                try:
                    raw = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                title = self._extract_title(raw) or path.stem.replace("_", " ").title()
                for idx, chunk in enumerate(self._split_text(raw)):
                    docs.append({
                        "id": f"doc::{path.relative_to(self.root_dir)}#{idx}",
                        "title": title,
                        "text": chunk,
                        "path": str(path.relative_to(self.root_dir)),
                        "source": "document",
                    })
        return docs

    @staticmethod
    def _extract_title(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("# ").strip()
            if stripped:
                return stripped
        return ""

    @staticmethod
    def _split_text(text: str, max_len: int = 500) -> List[str]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0
        for para in paragraphs:
            if current_len + len(para) > max_len and current:
                chunks.append(" ".join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)
        if current:
            chunks.append(" ".join(current))
        if not chunks and text.strip():
            chunks.append(text.strip())
        return chunks

    @staticmethod
    def _format_snippet(text: str, limit: int = 180) -> str:
        clean = " ".join(text.strip().split())
        if len(clean) <= limit:
            return clean
        cut = clean[: limit - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut + "…"

    @staticmethod
    def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
        if not vec_a or not vec_b:
            return 0.0
        length = min(len(vec_a), len(vec_b))
        dot = sum(vec_a[i] * vec_b[i] for i in range(length))
        norm_a = math.sqrt(sum(vec_a[i] * vec_a[i] for i in range(length))) or 1.0
        norm_b = math.sqrt(sum(vec_b[i] * vec_b[i] for i in range(length))) or 1.0
        return dot / (norm_a * norm_b)


_service: SemanticSearchService | None = None
_service_lock = asyncio.Lock()


def _get_root_dir() -> Path:
    return Path(__file__).resolve().parent.parent


async def get_search_service() -> SemanticSearchService:
    global _service
    async with _service_lock:
        if _service is None:
            _service = SemanticSearchService(root_dir=_get_root_dir())
        return _service
