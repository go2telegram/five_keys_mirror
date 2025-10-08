#!/usr/bin/env python3
"""Build the product catalog from description files and image assets."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen, url2pathname


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - optional dependency
    from python_slugify import slugify as _python_slugify  # type: ignore
except ImportError:  # pragma: no cover - fallback to vendored implementation
    _python_slugify = None

from slugify import slugify as _fallback_slugify


CATALOG_PATH = ROOT / "app" / "catalog" / "products.json"
SCHEMA_PATH = ROOT / "app" / "data" / "products.schema.json"

# descriptions source (один из)
DEFAULT_DESCRIPTIONS_URL = "https://github.com/go2telegram/media/tree/main/descriptions"
DEFAULT_DESCRIPTIONS_PATH = str(ROOT / "app" / "catalog" / "descriptions")

# images
DEFAULT_IMAGES_MODE = "local"  # or "remote"
DEFAULT_IMAGES_BASE = "https://raw.githubusercontent.com/go2telegram/media/main/media/products/"
DEFAULT_IMAGES_DIR = str(ROOT / "app" / "static" / "images" / "products")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ORDER_KEYWORDS = ("ссылка", "заказ")
SECTION_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "usage": (
        "как применять",
        "как использовать",
        "инструкция по применению",
        "рекомендации по применению",
        "рекомендации",
    ),
    "contra": ("противопоказания",),
    "composition": ("состав",),
}
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("drinks", ("чай", "кофе", "coffee", "какао", "напит*", "shot", "smoothie", "смузи")),
    (
        "supplements",
        (
            "омега",
            "omega",
            "витамин",
            "капсул*",
            "комплекс",
            "коллаген",
            "протеин",
            "желат",
            "пробиот",
            "аминокислот",
            "гель",
        ),
    ),
    ("accessories", ("очки", "шейкер", "аксессуар", "бутыл", "браслет")),
    ("cosmetics", ("сыворот", "маска", "крем", "уход", "серум")),
)
STOPWORDS = {"t8", "era", "nash", "t8era"}

BRAND_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:T8|Т8)\s+ERA\b", re.IGNORECASE),
    re.compile(r"^(?:T8|Т8)\b", re.IGNORECASE),
    re.compile(r"^NASH\b", re.IGNORECASE),
    re.compile(r"^VIMI\b", re.IGNORECASE),
    re.compile(r"^VITEN\b", re.IGNORECASE),
    re.compile(r"^ERA\b", re.IGNORECASE),
)

DESCRIPTION_OVERRIDES: Mapping[str, dict[str, str]] = {
    "t8-era-mit-up": {
        "usage": "По 1 стику в день утром за 30 минут до еды. Упаковка рассчитана на 21 день.",
    },
    "t8-blend-90": {
        "buy_url": "https://vlv-shop.ru/ru-ru/app/catalog/18/39090?ref=735861",
        "composition": "сывороточный протеин и таёжные ягоды помогают поддерживать организм.",
    },
    "t8-stekla-black-96": {
        "usage": "Надевать за 2 часа до сна.",
        "contra": "Нет.",
    },
}


class CatalogBuildError(RuntimeError):
    """Raised when the catalog cannot be built."""


@dataclass
class ProductBlock:
    lines: list[str]
    url: str | None
    origin: str


def quote_url(url: str) -> str:
    """Percent-encode the path and query components of a URL."""

    parts = urlsplit(url)
    path = quote(parts.path)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode(query_items, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _http_get(url: str, *, accept: str | None = None) -> bytes:
    quoted = quote_url(url)
    headers = {"User-Agent": "five-keys-bot/ingest"}
    if accept:
        headers["Accept"] = accept
    request = Request(quoted, headers=headers)
    try:
        with urlopen(request) as response:  # type: ignore[arg-type]
            return response.read()
    except OSError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Failed to fetch {url}: {exc}") from exc


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Cannot read {path}: {exc}") from exc


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _to_lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in text.split("\n")]


def _is_file_url(value: str) -> bool:
    return urlsplit(value).scheme == "file"


def _file_url_to_path(value: str) -> Path:
    parsed = urlsplit(value)
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        raise CatalogBuildError(f"Unsupported file URL host: {value}")
    return Path(url2pathname(parsed.path))


def _list_local_texts(path: Path) -> list[tuple[str, str]]:
    if path.is_file():
        return [(str(path), _read_text(path))]
    if path.is_dir():
        items: list[tuple[str, str]] = []
        for file in sorted(path.rglob("*.txt")):
            items.append((str(file), _read_text(file)))
        if not items:
            raise CatalogBuildError(f"No .txt files found in {path}")
        return items
    raise CatalogBuildError(f"Unknown descriptions source {path}")


def _parse_github_tree(url: str) -> tuple[str, str, str, str]:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) < 4:
        raise CatalogBuildError(f"Cannot parse GitHub URL {url}")
    owner, repo, marker, *rest = parts
    if marker == "tree":
        ref = rest[0]
        path = "/".join(rest[1:])
    else:  # raw.githubusercontent.com
        ref = rest[1]
        path = "/".join(rest[2:])
    return owner, repo, ref, path


def _github_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    *,
    extensions: set[str] | None = None,
) -> list[dict[str, str]]:
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    payload = json.loads(_http_get(api, accept="application/vnd.github+json"))
    entries: list[dict[str, str]] = []
    if isinstance(payload, dict) and payload.get("type") == "file":
        download = payload.get("download_url")
        if download:
            if not extensions or Path(download).suffix.lower() in extensions:
                entries.append({"download_url": download, "path": payload.get("path", path)})
        return entries
    if not isinstance(payload, list):
        raise CatalogBuildError(f"Unexpected GitHub API response for {path}")
    for item in payload:
        if item.get("type") == "dir":
            entries.extend(
                _github_contents(
                    owner,
                    repo,
                    item.get("path", ""),
                    ref,
                    extensions=extensions,
                )
            )
            continue
        if item.get("type") != "file":
            continue
        download = item.get("download_url")
        if not download:
            continue
        if extensions and Path(download).suffix.lower() not in extensions:
            continue
        entries.append({"download_url": download, "path": item.get("path", "")})
    if not entries:
        raise CatalogBuildError(f"No description files found at {path}")
    entries.sort(key=lambda item: item.get("path", ""))
    return entries


def _coerce_sources(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        stripped = str(item).strip()
        if stripped:
            normalized.append(stripped)
    return normalized


def _load_description_texts(
    *, descriptions_url: str | Sequence[str] | None, descriptions_path: str | Sequence[str] | None
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []

    for path_value in _coerce_sources(descriptions_path):
        items.extend(_list_local_texts(Path(path_value)))

    for url_value in _coerce_sources(descriptions_url):
        if _is_file_url(url_value):
            items.extend(_list_local_texts(_file_url_to_path(url_value)))
            continue
        if url_value.lower().endswith(".txt"):
            text = _http_get(url_value).decode("utf-8")
            items.append((url_value, text))
            continue
        owner, repo, ref, path = _parse_github_tree(url_value)
        entries = _github_contents(owner, repo, path, ref, extensions={".txt"})
        for entry in entries:
            download_url = entry["download_url"]
            items.append((download_url, _http_get(download_url).decode("utf-8")))

    if items:
        return items

    if DEFAULT_DESCRIPTIONS_PATH:
        local_path = Path(DEFAULT_DESCRIPTIONS_PATH)
        if local_path.exists():
            return _list_local_texts(local_path)
    return _load_description_texts(descriptions_url=DEFAULT_DESCRIPTIONS_URL, descriptions_path=None)


def _normalize_heading(value: str) -> str:
    normalized = value.lower().replace("ё", "е")
    normalized = re.sub(r"[^a-zа-я0-9 ]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _is_order_marker(line: str) -> bool:
    normalized = _normalize_heading(line)
    return all(keyword in normalized for keyword in ORDER_KEYWORDS)


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_url(line: str) -> str | None:
    match = URL_RE.search(line)
    return match.group(0) if match else None


def _clean_lines(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if re.fullmatch(r"[\-=*_]{3,}", stripped):
            continue
        cleaned.append(stripped)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def _join_paragraphs(lines: Sequence[str]) -> str:
    items = list(lines)
    while items and not items[-1]:
        items.pop()
    return "\n".join(items).strip()


def _split_blocks(text: str, *, origin: str) -> list[ProductBlock]:
    lines = _to_lines(_strip_bom(text))
    blocks: list[ProductBlock] = []
    buffer: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_order_marker(line):
            url = _extract_url(line)
            j = i + 1
            while not url and j < len(lines):
                candidate = lines[j]
                url = _extract_url(candidate)
                if url:
                    i = j
                    break
                if candidate.strip():
                    break
                j += 1
            blocks.append(ProductBlock(lines=_clean_lines(buffer), url=url, origin=origin))
            buffer = []
        else:
            buffer.append(line)
        i += 1
    return [block for block in blocks if block.lines and block.url]


def _split_sentences(text: str) -> list[str]:
    sentences = re.findall(r"[^.!?]+[.!?]", text)
    if not sentences:
        return [text] if text else []
    return [sentence.strip() for sentence in sentences]


def _section_for_line(line: str) -> tuple[str, str] | None:
    parts = re.split(r"[:：]\s*", line, maxsplit=1)
    heading = _normalize_heading(parts[0])
    for key, names in SECTION_KEYWORDS.items():
        if any(heading.startswith(name) for name in names):
            remainder = parts[1].strip() if len(parts) > 1 else ""
            return key, remainder
    return None


def _classify_category(text: str) -> str:
    normalized = _normalize_heading(text)
    words = [word for word in re.split(r"\s+", normalized) if word]
    for slug, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword.endswith("*"):
                stem = keyword[:-1]
                if any(word.startswith(stem) for word in words):
                    return slug
            else:
                if keyword in words:
                    return slug
    return "general"


def _normalize_title_candidate(text: str) -> str:
    candidate = text.strip().strip("«»\"'“”")
    if not candidate:
        return ""
    candidate = re.split(r"[—–]", candidate, maxsplit=1)[0].strip()
    suffix_numbers: list[str] = []
    for match in re.findall(r"\(([^)]*)\)", candidate):
        digits = re.findall(r"\d+", match)
        if not digits:
            continue
        if re.search(r"%(?:\s|$)", match) or re.search(r"капсул", match, re.IGNORECASE):
            suffix_numbers.extend(digits)
    candidate = re.sub(r"\s*\([^)]*\)", "", candidate).strip()
    candidate = re.sub(r"\s+с\s+[^,]+$", "", candidate, flags=re.IGNORECASE)
    if suffix_numbers:
        candidate = f"{candidate} {' '.join(suffix_numbers)}".strip()
    return candidate


def _has_brand_prefix(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    return any(pattern.match(normalized) for pattern in BRAND_NAME_PATTERNS)


def _canonical_title(lines: Sequence[str]) -> str:
    if not lines:
        raise CatalogBuildError("Empty product block")
    primary = _normalize_title_candidate(lines[0])
    if _has_brand_prefix(primary):
        return primary
    for line in lines[1:]:
        if not line.strip():
            break
        candidate = _normalize_title_candidate(line)
        if _has_brand_prefix(candidate):
            return candidate
    return primary


def _slug(text: str) -> str:
    prepared = text.replace("Ё", "Е").replace("ё", "е")
    if _python_slugify is not None:
        return _python_slugify(prepared, lowercase=True, language="ru")
    return _fallback_slugify(prepared, lowercase=True, language="ru")


def _normalize_slug_value(slug_value: str) -> str:
    value = slug_value.strip()
    if re.search(r"[А-Яа-яЁё]", value):
        return _slug(value)
    slug = value.lower().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _tokenize_slug(slug_value: str) -> list[str]:
    normalized = _normalize_slug_value(slug_value)
    tokens = [token for token in re.split(r"[-_]+", normalized) if token]
    return [token for token in tokens if token not in STOPWORDS]


def _refine_slug(slug_value: str) -> str:
    tokens = [token for token in slug_value.split("-") if token]
    if tokens and tokens[-1] in {"kapsul", "capsules"}:
        tokens.pop()
    if tokens and tokens[-1].isdigit():
        last = int(tokens[-1])
        if last <= 50 and not (len(tokens) >= 2 and tokens[-2] in {"omega"}):
            tokens.pop()
    return "-".join(tokens) if tokens else slug_value


def _slug_aliases(slug_value: str) -> set[str]:
    normalized = _normalize_slug_value(slug_value)
    tokens = _tokenize_slug(normalized)
    joined = "".join(tokens)
    without_digits = "".join(token for token in tokens if not token.isdigit())
    stripped_digits = re.sub(r"[0-9]+", "", normalized)
    stripped_digits = re.sub(r"-+", "-", stripped_digits).strip("-")
    variants = {
        normalized,
        normalized.replace("-", ""),
        normalized.replace("-", "_"),
        joined,
        without_digits,
        re.sub(r"[^a-z0-9]+", "", normalized),
        stripped_digits,
    }
    variants.update(tokens)
    for prefix in ("t8-era-", "t8-", "nash-"):
        if normalized.startswith(prefix):
            variants.add(normalized[len(prefix) :])
    parts = normalized.split("-")
    if len(parts) > 1 and parts[-1].isdigit():
        without_last = "-".join(parts[:-1])
        if without_last:
            variants.add(without_last)
            variants.add(without_last.replace("-", "_"))
    return {variant for variant in variants if variant}


def _alias_variants(slug_value: str) -> list[str]:
    return sorted(_slug_aliases(slug_value))


def _build_aliases(product_id: str) -> list[str]:
    return _alias_variants(product_id)


def _parse_block(block: ProductBlock) -> dict[str, object]:
    if not block.url:
        raise CatalogBuildError(f"Missing order URL in {block.origin}")
    lines = block.lines
    if not lines:
        raise CatalogBuildError(f"Empty product block in {block.origin}")
    name = lines[0]
    canonical_name = _canonical_title(lines)
    remainder = lines[1:]
    section_data: dict[str, list[str]] = defaultdict(list)
    body: list[str] = []
    current = "body"
    for line in remainder:
        if not line:
            if current == "body":
                body.append("")
            else:
                section_data[current].append("")
            continue
        section = _section_for_line(line)
        if section:
            current = section[0]
            if section[1]:
                section_data[current].append(section[1])
            continue
        if current == "body":
            body.append(line)
        else:
            section_data[current].append(line)
    description = _join_paragraphs(body)
    sentences = _split_sentences(_normalize_space(description))
    short = " ".join(sentences[:2]) if sentences else ""
    usage = _join_paragraphs([part for part in section_data.get("usage", []) if part])
    contra = _join_paragraphs([part for part in section_data.get("contra", []) if part])
    composition = _join_paragraphs(
        [part for part in section_data.get("composition", []) if part]
    )
    category = _classify_category(name + "\n" + description)
    product_id = _refine_slug(_slug(canonical_name))
    tags = sorted({token for token in _tokenize_slug(product_id) if token})
    data: dict[str, object] = {
        "id": product_id,
        "title": name,
        "name": name,
        "short": short or description,
        "description": description,
        "category": category,
        "tags": tags,
        "order": {"velavie_link": block.url},
        "available": True,
    }
    if usage:
        data["usage"] = usage
    if contra:
        data["contra"] = contra
    if composition:
        data["composition"] = composition
    overrides = DESCRIPTION_OVERRIDES.get(product_id)
    if overrides:
        for key, value in overrides.items():
            if key == "buy_url":
                data.setdefault("order", {})
                order = data["order"]
                if isinstance(order, dict):
                    order["velavie_link"] = value
            else:
                data[key] = value
    return data


def _load_products(texts: list[tuple[str, str]]) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    for origin, text in texts:
        for block in _split_blocks(text, origin=origin):
            products.append(_parse_block(block))
    if not products:
        raise CatalogBuildError("No products parsed from descriptions")
    return products


def _dedupe_products(
    products: Iterable[dict[str, object]], *, dedupe: bool = True, strict: bool = False
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for product in products:
        title = str(product.get("title", "")).strip()
        order = product.get("order") if isinstance(product.get("order"), dict) else None
        url = ""
        if isinstance(order, dict):
            url = str(order.get("velavie_link", "")).strip()
        if not title or not url:
            continue
        product["title"] = title
        product["name"] = title
        if isinstance(order, dict):
            order["velavie_link"] = url
        key = (title.lower(), url)
        if dedupe and key in seen:
            duplicates.append((title, url))
            if strict:
                raise CatalogBuildError(
                    f"Duplicate product description for '{title}' ({url})"
                )
            continue
        seen.add(key)
        normalized.append(product)
    if not normalized:
        raise CatalogBuildError("No products parsed from descriptions")
    if strict and duplicates:
        titles = ", ".join(sorted({title for title, _ in duplicates}))
        raise CatalogBuildError(f"Duplicate product descriptions detected: {titles}")
    return normalized


def _list_remote_images(images_base: str) -> tuple[str, list[str]]:
    if images_base.endswith("/"):
        images_base = images_base[:-1]
    owner, repo, ref, path = _parse_github_tree(images_base)
    entries = _github_contents(owner, repo, path, ref, extensions=IMAGE_EXTENSIONS)
    files = [Path(item["path"]).name for item in entries if item.get("download_url")]
    return images_base + "/", sorted(set(files))


def _normalize_image_relative_path(relative: Path) -> tuple[Path, bool]:
    parts = list(relative.parts)
    trimmed = False
    while parts and parts[0] == "images":
        parts = parts[1:]
        trimmed = True
    normalized = Path(*parts) if parts else Path(relative.name)
    return normalized, trimmed


def normalize_images_directory(images_dir: Path) -> bool:
    """Physically flatten nested images directories, returning True when changes were made."""

    if not images_dir.exists() or not images_dir.is_dir():
        return False

    nested = images_dir / "images"
    if not nested.is_dir():
        return False

    logging.warning("Nested images directory detected: %s — flattening", nested)
    modified = False
    conflicts = False
    files = [path for path in nested.rglob("*") if path.is_file()]
    for source in sorted(files):
        relative = source.relative_to(nested)
        target_relative, _ = _normalize_image_relative_path(relative)
        target = images_dir / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            conflicts = True
            logging.error("Cannot move %s to %s: target already exists", source, target)
            continue
        source.rename(target)
        modified = True
    if not conflicts:
        try:
            for directory in sorted(nested.glob("**/*"), reverse=True):
                if directory.is_dir():
                    directory.rmdir()
        except OSError:
            pass
        try:
            nested.rmdir()
        except OSError:
            pass
    return modified


def _list_local_images(images_dir: Path) -> list[str]:
    if not images_dir.exists():
        raise CatalogBuildError(f"Images directory {images_dir} not found")
    normalized: list[str] = []
    warned = False
    for file in images_dir.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative = file.relative_to(images_dir)
        normalized_path, trimmed = _normalize_image_relative_path(relative)
        if trimmed and not warned:
            logging.warning(
                "Nested images directory detected under %s — treating as flattened", images_dir
            )
            warned = True
        normalized.append(normalized_path.as_posix())
    return sorted(set(normalized))


def _local_web_base(images_dir: Path) -> str:
    directory = images_dir
    if not directory.is_absolute():
        directory = (ROOT / directory).resolve()
    try:
        relative = directory.relative_to((ROOT / "app").resolve())
        web_base = "/" + relative.as_posix()
    except ValueError:
        try:
            relative = directory.relative_to(ROOT)
            web_base = "/" + relative.as_posix()
        except ValueError:
            web_base = "/" + directory.as_posix().lstrip("./")
    if not web_base.endswith("/"):
        web_base += "/"
    return web_base


@dataclass(frozen=True)
class ImageMatch:
    name: str
    alias: str | None = None
    score: int = 0


def _match_image(slug_value: str, candidates: list[str]) -> ImageMatch | None:
    slug_lower = _normalize_slug_value(slug_value)
    aliases = _slug_aliases(slug_lower)
    sanitized_slug = re.sub(r"[^a-z0-9]", "", slug_lower)
    prioritized: list[tuple[int, int, str | None, str]] = []
    for candidate in candidates:
        path = Path(candidate)
        suffix = path.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            continue
        stem = path.stem
        candidate_slug = _normalize_slug_value(stem)
        candidate_aliases = _slug_aliases(candidate_slug)
        sanitized = re.sub(r"[^a-z0-9]", "", candidate_slug)
        alias_intersection = aliases.intersection(candidate_aliases)
        alias_candidates = [alias for alias in alias_intersection if alias != slug_lower]
        alias_used = min(alias_candidates, key=len) if alias_candidates else None
        score: int | None = None
        if candidate_slug == slug_lower:
            score = 0
        elif candidate_slug.startswith(slug_lower) and "main" in candidate_slug[len(slug_lower):]:
            score = 1
        elif sanitized_slug and sanitized == sanitized_slug:
            score = 2
        elif sanitized_slug and sanitized.startswith(sanitized_slug) and "main" in sanitized[len(sanitized_slug):]:
            score = 3
        elif alias_intersection:
            score = 4
            if alias_used is None:
                alias_used = min(alias_intersection, key=len)
        elif sanitized_slug and sanitized.startswith(sanitized_slug):
            score = 5
        else:
            continue
        main_bonus = 0 if "main" in candidate_slug else 1
        prioritized.append((score, main_bonus, alias_used, candidate))
    if prioritized:
        prioritized.sort(key=lambda item: (item[0], item[1], item[3]))
        score, _main_bonus, alias_used, candidate = prioritized[0]
        return ImageMatch(name=candidate, alias=alias_used, score=score)
    return None


def _choose_image(slug_value: str, candidates: list[str]) -> str | None:
    match = _match_image(slug_value, candidates)
    return match.name if match else None


def _resolve_image(
    product: dict[str, object],
    *,
    image_files: list[str],
    image_mode: str,
    image_base: str,
    strict: bool = False,
) -> None:
    product_id = str(product["id"])
    match = _match_image(product_id, image_files)
    if not match:
        message = f"No image for {product_id}"
        if strict:
            raise CatalogBuildError(message)
        logging.warning(message)
        product["available"] = False
        fallback = image_base if image_base.endswith("/") else image_base + "/"
        fallback += f"{product_id}.jpg"
        product["image"] = fallback
        product["images"] = [fallback]
        return
    if match.alias is not None and match.alias != product_id:
        aliases = _build_aliases(product_id)
        if aliases:
            product["aliases"] = aliases
    image_name = match.name
    if image_mode == "remote":
        base = image_base if image_base.endswith("/") else image_base + "/"
        url = urljoin(base, image_name)
        product["image"] = url
        product["images"] = [url]
    else:
        base = image_base if image_base.endswith("/") else image_base + "/"
        rel_path = image_name.replace("\\", "/")
        product["image"] = base + rel_path
        product["images"] = [product["image"]]


def _merge_utm(url: str, product_id: str, category: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    utm_defaults = {
        "utm_source": "tg_bot",
        "utm_medium": "catalog",
        "utm_campaign": _slug(category or "catalog"),
        "utm_content": product_id,
    }

    def _ensure_item(key: str, value: str) -> None:
        for index, (existing_key, existing_value) in enumerate(query_items):
            if existing_key != key:
                continue
            if existing_value:
                return
            query_items[index] = (existing_key, value)
            return
        query_items.append((key, value))

    for key, default_value in utm_defaults.items():
        _ensure_item(key, default_value)

    normalized_query = urlencode(query_items, doseq=True)
    normalized_url = urlunsplit(
        parsed._replace(path=quote(parsed.path), query=normalized_query)
    )

    utm_values: dict[str, str] = {}
    for key in utm_defaults:
        for existing_key, existing_value in query_items:
            if existing_key == key:
                utm_values[key] = existing_value
                break

    return normalized_url, utm_values


def build_catalog(
    *,
    descriptions_url: str | Sequence[str] | None = None,
    descriptions_path: str | Sequence[str] | None = None,
    images_mode: str | None = None,
    images_base: str | None = None,
    images_dir: str | None = None,
    output: Path | None = None,
    dedupe: bool = True,
    strict_images: bool = False,
    strict_descriptions: bool = False,
    expect_count: int | None = None,
    fail_on_mismatch: bool = False,
) -> tuple[int, Path]:
    texts = _load_description_texts(
        descriptions_url=descriptions_url,
        descriptions_path=descriptions_path,
    )
    products = _dedupe_products(
        _load_products(texts), dedupe=dedupe, strict=strict_descriptions
    )

    mode = (images_mode or DEFAULT_IMAGES_MODE).lower()
    if mode not in {"remote", "local"}:
        raise CatalogBuildError("images-mode must be 'remote' or 'local'")

    if mode == "remote":
        base = images_base or DEFAULT_IMAGES_BASE
        image_base, files = _list_remote_images(base)
    else:
        directory = Path(images_dir or DEFAULT_IMAGES_DIR)
        files = _list_local_images(directory)
        image_base = _local_web_base(directory)
    unique_ids: set[str] = set()
    normalized: list[dict[str, object]] = []
    for product in products:
        product_id = str(product["id"])
        if product_id in unique_ids:
            message = f"Duplicate product id {product_id}"
            if strict_descriptions:
                raise CatalogBuildError(message)
            logging.warning(message)
            continue
        unique_ids.add(product_id)
        url = str(product["order"]["velavie_link"])
        quoted_url, utm = _merge_utm(url, product_id, str(product.get("category", "")))
        product["order"] = {
            "velavie_link": quoted_url,
            "utm": utm,
        }
        _resolve_image(
            product,
            image_files=files,
            image_mode=mode,
            image_base=image_base,
            strict=strict_images,
        )
        normalized.append(product)

    normalized.sort(key=lambda item: str(item.get("title", "")))
    destination = output or CATALOG_PATH
    payload = {"products": normalized}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    count = len(normalized)
    if expect_count is not None and count != expect_count:
        mismatch = (
            "Built product count mismatch: "
            f"expected {expect_count}, got {count}"
        )
        if fail_on_mismatch:
            raise CatalogBuildError(mismatch)
        logging.warning(mismatch)
    return count, destination


def validate_catalog(path: Path | None = None) -> int:
    target = path or CATALOG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Cannot read catalog file {target}: {exc}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise CatalogBuildError(f"Catalog file {target} is not valid JSON") from exc
    products = data.get("products")
    if not isinstance(products, list) or not products:
        raise CatalogBuildError("Catalog must contain a non-empty 'products' list")
    seen: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            raise CatalogBuildError("Catalog product must be an object")
        product_id = str(product.get("id", "")).strip()
        if not product_id:
            raise CatalogBuildError("Catalog product missing id")
        if product_id in seen:
            raise CatalogBuildError(f"Duplicate product id {product_id}")
        seen.add(product_id)
        order = product.get("order")
        if not isinstance(order, dict) or "velavie_link" not in order:
            raise CatalogBuildError(f"{product_id}: missing order.velavie_link")
        url = order["velavie_link"]
        if not isinstance(url, str) or not url.strip():
            raise CatalogBuildError(f"{product_id}: order.velavie_link must be a non-empty string")
        params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
            if not params.get(key):
                raise CatalogBuildError(f"{product_id}: missing {key} utm parameter")
        image = product.get("image")
        images = product.get("images")
        if image is not None and not isinstance(image, str):
            raise CatalogBuildError(f"{product_id}: image must be a string")
        if not isinstance(images, list) or not images:
            raise CatalogBuildError(f"{product_id}: images must be a non-empty list")
        first_image = images[0]
        if not isinstance(first_image, str):
            raise CatalogBuildError(f"{product_id}: images[0] must be a string")
        if image is not None and first_image != image:
            raise CatalogBuildError(f"{product_id}: image and images[0] must be identical")
    return len(products)


def _build_cli(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the catalog products file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Fetch descriptions and build the catalog")
    build_parser.add_argument("--descriptions-url", action="append", default=None)
    build_parser.add_argument("--descriptions-path", action="append", default=None)
    build_parser.add_argument("--images-mode", choices=("remote", "local"), default=None)
    build_parser.add_argument("--images-base", default=None)
    build_parser.add_argument("--images-dir", default=None)
    build_parser.add_argument("--output", type=Path, default=None)
    build_parser.add_argument("--dedupe", choices=("on", "off"), default="on")
    build_parser.add_argument("--strict-images", action="store_true", help="Fail if a product image cannot be resolved")
    build_parser.add_argument(
        "--strict-descriptions",
        action="store_true",
        help="Fail on duplicate product descriptions or identifiers",
    )
    build_parser.add_argument(
        "--expect-count",
        type=int,
        default=None,
        help="Expected number of products in the generated catalog",
    )
    build_parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit with an error if the built product count mismatches --expect-count",
    )

    validate_parser = subparsers.add_parser("validate", help="Validate an existing catalog file")
    validate_parser.add_argument("--source", type=Path, default=CATALOG_PATH)

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command == "build":
            count, path = build_catalog(
                descriptions_url=args.descriptions_url,
                descriptions_path=args.descriptions_path,
                images_mode=args.images_mode,
                images_base=args.images_base,
                images_dir=args.images_dir,
                output=args.output,
                dedupe=args.dedupe != "off",
                strict_images=args.strict_images,
                strict_descriptions=args.strict_descriptions,
                expect_count=args.expect_count,
                fail_on_mismatch=args.fail_on_mismatch,
            )
            print(f"Built catalog with {count} products → {path}")
            return 0
        if args.command == "validate":
            count = validate_catalog(args.source)
            print(f"Catalog OK ({count} products)")
            return 0
    except CatalogBuildError as exc:
        logging.error("%s", exc)
        return 1
    raise CatalogBuildError("Unknown command")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
