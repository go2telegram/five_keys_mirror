"""Utilities for synchronising vector knowledge indexes across clusters."""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx
from aiohttp import web

from app.config import settings

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """Return True when global knowledge sync is enabled via settings."""
    return bool(getattr(settings, "ENABLE_GLOBAL_KNOWLEDGE_SYNC", False))


@dataclass(slots=True)
class KnowledgeIndexMeta:
    """Metadata about a single knowledge index file."""

    path: str
    md5: str
    size: int
    modified: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "md5": self.md5,
            "size": self.size,
            "modified": self.modified,
        }


class KnowledgeSyncService:
    """Synchronises local knowledge indexes with remote peers."""

    def __init__(
        self,
        index_dir: Path,
        peers: Sequence[str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.peers = [p.rstrip("/") for p in (peers or []) if p.strip()]
        self.timeout = timeout

    @classmethod
    def from_settings(cls, cfg=settings) -> "KnowledgeSyncService":
        index_dir = Path(getattr(cfg, "KNOWLEDGE_INDEX_DIR", "storage/knowledge"))
        peers_raw = getattr(cfg, "GLOBAL_KNOWLEDGE_SYNC_PEERS", "")
        peers = [item.strip() for item in peers_raw.split(",") if item.strip()]
        timeout = float(getattr(cfg, "GLOBAL_KNOWLEDGE_SYNC_TIMEOUT", 30.0))
        return cls(index_dir=index_dir, peers=peers, timeout=timeout)

    # ------------------------------------------------------------------
    # API handlers
    # ------------------------------------------------------------------
    async def handle_request(self, request: web.Request) -> web.Response:
        if not is_enabled():
            raise web.HTTPForbidden(text="Global knowledge sync is disabled")
        try:
            payload = await request.json()
        except Exception as exc:  # aiohttp raises ContentTypeError/JSONDecodeError
            raise web.HTTPBadRequest(text=f"Invalid JSON payload: {exc}") from exc

        action = payload.get("action")
        if action == "pull":
            known = payload.get("known") or []
            result = self._handle_pull(known)
        elif action == "push":
            indexes = payload.get("indexes") or []
            removed = payload.get("removed") or []
            result = self._handle_push(indexes, removed)
        else:
            raise web.HTTPBadRequest(text="Unsupported action. Use 'push' or 'pull'.")

        return web.json_response(result)

    # ------------------------------------------------------------------
    # Local index operations
    # ------------------------------------------------------------------
    def _handle_pull(self, known: Iterable[dict[str, Any]]) -> dict[str, Any]:
        known_map = {item.get("path"): item.get("md5") for item in known if item.get("path")}
        local_map = self._collect_index_metadata()

        changed_indexes: list[dict[str, Any]] = []
        for path, meta in local_map.items():
            if known_map.get(path) != meta.md5:
                changed_indexes.append(self._prepare_index_payload(path))

        removed = [path for path in known_map if path not in local_map]

        logger.debug(
            "Prepared pull payload: %s changed, %s removed", len(changed_indexes), len(removed)
        )
        return {
            "indexes": changed_indexes,
            "removed": removed,
            "inventory": [meta.to_dict() for meta in local_map.values()],
        }

    def _handle_push(
        self,
        indexes: Iterable[dict[str, Any]],
        removed: Iterable[str],
    ) -> dict[str, Any]:
        applied = 0
        skipped = 0
        removed_count = 0

        for item in indexes:
            try:
                if self._apply_index(item):
                    applied += 1
                else:
                    skipped += 1
            except ValueError as exc:
                skipped += 1
                logger.warning("Failed to apply index %s: %s", item.get("path"), exc)

        for rel_path in removed:
            try:
                if self._delete_index(rel_path):
                    removed_count += 1
            except ValueError as exc:
                logger.warning("Failed to delete index %s: %s", rel_path, exc)

        inventory = [meta.to_dict() for meta in self._collect_index_metadata().values()]
        return {
            "applied": applied,
            "skipped": skipped,
            "removed": removed_count,
            "inventory": inventory,
        }

    # ------------------------------------------------------------------
    # Public sync operations
    # ------------------------------------------------------------------
    async def sync_with_peers(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not self.peers:
            logger.debug("Knowledge sync: no peers configured")
            return results

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for peer in self.peers:
                try:
                    peer_result = await self._sync_with_peer(client, peer)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Knowledge sync with %s failed: %s", peer, exc)
                    peer_result = {"peer": peer, "error": str(exc)}
                results.append(peer_result)
        return results

    async def _sync_with_peer(self, client: httpx.AsyncClient, peer: str) -> dict[str, Any]:
        url = f"{peer}/knowledge_sync" if not peer.endswith("/knowledge_sync") else peer
        local_metadata = [meta.to_dict() for meta in self._collect_index_metadata().values()]

        logger.debug("Pulling knowledge indexes from %s", url)
        pull_response = await client.post(url, json={"action": "pull", "known": local_metadata})
        pull_response.raise_for_status()
        payload = pull_response.json()

        remote_indexes = payload.get("indexes", [])
        remote_removed = payload.get("removed", [])
        remote_inventory = payload.get("inventory", [])

        applied_result = self._handle_push(remote_indexes, remote_removed)
        local_after_pull = self._collect_index_metadata()

        remote_map = {item.get("path"): item.get("md5") for item in remote_inventory if item.get("path")}
        to_push = [
            meta.path
            for meta in local_after_pull.values()
            if remote_map.get(meta.path) != meta.md5
        ]

        push_result: dict[str, Any] = {"applied": 0, "skipped": 0, "removed": 0, "inventory": []}
        if to_push:
            logger.debug("Pushing %s indexes to %s", len(to_push), url)
            indexes_payload = [self._prepare_index_payload(path) for path in to_push]
            push_response = await client.post(
                url, json={"action": "push", "indexes": indexes_payload, "removed": []}
            )
            push_response.raise_for_status()
            push_result = push_response.json()

        drift = self._calculate_drift(local_after_pull, push_result.get("inventory", []))
        if drift > 0.01:
            logger.warning("Knowledge sync drift %.2f%% with %s", drift * 100, peer)

        return {
            "peer": peer,
            "pulled": {
                "applied": applied_result["applied"],
                "skipped": applied_result["skipped"],
                "removed": applied_result["removed"],
            },
            "pushed": {
                "applied": push_result.get("applied", 0),
                "skipped": push_result.get("skipped", 0),
            },
            "drift": drift,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _collect_index_metadata(self) -> dict[str, KnowledgeIndexMeta]:
        meta: dict[str, KnowledgeIndexMeta] = {}
        for file_path in self.index_dir.rglob("*"):
            if not file_path.is_file():
                continue
            rel_path = str(file_path.relative_to(self.index_dir))
            data = file_path.read_bytes()
            checksum = hashlib.md5(data).hexdigest()
            stat = file_path.stat()
            meta[rel_path] = KnowledgeIndexMeta(
                path=rel_path,
                md5=checksum,
                size=len(data),
                modified=stat.st_mtime,
            )
        return meta

    def _prepare_index_payload(self, rel_path: str) -> dict[str, Any]:
        file_path = self._resolve_path(rel_path)
        data = file_path.read_bytes()
        checksum = hashlib.md5(data).hexdigest()
        return {
            "path": rel_path,
            "md5": checksum,
            "size": len(data),
            "content": base64.b64encode(data).decode("ascii"),
        }

    def _apply_index(self, item: dict[str, Any]) -> bool:
        rel_path = item.get("path")
        content_b64 = item.get("content")
        md5_expected = item.get("md5")
        if not rel_path or not content_b64:
            return False

        data = base64.b64decode(content_b64)
        checksum = hashlib.md5(data).hexdigest()
        if md5_expected and md5_expected != checksum:
            raise ValueError("MD5 mismatch for index")

        file_path = self._resolve_path(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return True

    def _delete_index(self, rel_path: str) -> bool:
        file_path = self._resolve_path(rel_path)
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def _resolve_path(self, rel_path: str) -> Path:
        rel = Path(rel_path)
        base_dir = self.index_dir.resolve()
        full_path = (base_dir / rel).resolve()
        try:
            full_path.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError("Invalid index path") from exc
        return full_path

    @staticmethod
    def _calculate_drift(
        local_meta: dict[str, KnowledgeIndexMeta],
        remote_inventory: Iterable[dict[str, Any]],
    ) -> float:
        remote_map = {
            item.get("path"): item.get("md5") for item in remote_inventory if item.get("path")
        }
        if not local_meta and not remote_map:
            return 0.0

        mismatches = 0
        for path, meta in local_meta.items():
            if remote_map.get(path) != meta.md5:
                mismatches += 1
        for path in remote_map:
            if path not in local_meta:
                mismatches += 1

        total = max(len(local_meta), len(remote_map), 1)
        return mismatches / total


_SERVICE: KnowledgeSyncService | None = None


def get_service() -> KnowledgeSyncService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = KnowledgeSyncService.from_settings()
    return _SERVICE


async def handle_knowledge_sync(request: web.Request) -> web.Response:
    service = get_service()
    return await service.handle_request(request)
