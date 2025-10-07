#!/usr/bin/env python3
"""Build the product catalog from remote media descriptions."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from urllib.parse import (
    ParseResult,
    parse_qsl,
    quote,
    urlencode,
    urlparse,
    urlunparse,
)
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog" / "products.json"
SCHEMA_PATH = ROOT / "app" / "data" / "products.schema.json"

DEFAULT_DESCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/go2telegram/media/main/descriptions/"
)
DEFAULT_IMAGES_BASE = (
    "https://raw.githubusercontent.com/go2telegram/media/main/media/products"
)


class CatalogBuildError(RuntimeError):
    """Raised when catalog data cannot be built."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Cannot read {path}: {exc}") from exc


def _http_get(url: str, *, accept: str | None = None) -> bytes:
    headers = {
        "User-Agent": "five-keys-bot-build/1.0",
    }
    if accept:
        headers["Accept"] = accept
    request = Request(url, headers=headers)
    try:
        with urlopen(request) as response:  # type: ignore[call-arg]
            return response.read()
    except OSError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Failed to fetch {url}: {exc}") from exc


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _to_lines(text: str) -> Iterator[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        yield line.rstrip()


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


SPLIT_RE = re.compile(r"\n(?:(?:=|-|\*|_){4,}|\s*-\s*-\s*-\s*)\n")


FIELD_ALIASES: Mapping[str, str] = {
    "id": "id",
    "код": "id",
    "артикул": "id",
    "sku": "id",
    "title": "title",
    "название": "title",
    "product": "title",
    "имя": "title",
    "name": "title",
    "short": "short",
    "кратко": "short",
    "коротко": "short",
    "summary": "short",
    "описание": "description",
    "описание продукта": "description",
    "детали": "description",
    "description": "description",
    "состав": "composition",
    "composition": "composition",
    "benefits": "benefits",
    "преимущества": "benefits",
    "применение": "usage",
    "как принимать": "usage",
    "рекомендации": "usage",
    "usage": "usage",
    "противопоказания": "contra",
    "contra": "contra",
    "category": "category",
    "категория": "category",
    "группа": "category",
    "теги": "tags",
    "tags": "tags",
    "ключевые слова": "tags",
    "aliases": "aliases",
    "синонимы": "aliases",
    "order": "buy_url",
    "buy": "buy_url",
    "buy_url": "buy_url",
    "url": "buy_url",
    "ссылка": "buy_url",
    "ссылка на покупку": "buy_url",
    "link": "buy_url",
    "кнопка": "buy_url",
    "order_url": "buy_url",
    "available": "available",
}


KEY_VALUE_RE = re.compile(r"^\s*([^:：]+?)\s*[:：]\s*(.*)$")


def _normalize_key(raw: str) -> str | None:
    normalized = _normalize_whitespace(raw.lower())
    normalized = normalized.replace("ё", "е")
    return FIELD_ALIASES.get(normalized)


@dataclass
class RawProduct:
    """Intermediate representation of a product entry."""

    fields: dict[str, str] = field(default_factory=dict)
    blocks: dict[str, list[str]] = field(default_factory=dict)
    origin: str | None = None

    def set_value(self, key: str, value: str) -> None:
        if key in {"tags", "aliases"}:
            items = _split_list(value)
            if items:
                self.blocks[key] = items
            return
        if key == "available":
            value = value.lower()
            if value in {"false", "нет", "no", "0"}:
                self.fields[key] = "false"
            elif value:
                self.fields[key] = "true"
            return
        if key == "buy_url":
            self.fields[key] = value.strip()
            return
        if key in {"description", "usage", "contra", "composition", "benefits"}:
            lines = [line for line in _to_lines(value) if line]
            if lines:
                self.blocks[key] = lines
            return
        self.fields[key] = value.strip()

    def merge_multiline(self, key: str, lines: list[str]) -> None:
        text = "\n".join(line.rstrip() for line in lines).strip()
        if not text:
            return
        self.set_value(key, text)

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = dict(self.fields)
        for key, value in self.blocks.items():
            if key in {"tags", "aliases"}:
                data[key] = value
            else:
                data[key] = "\n".join(value)
        if self.origin:
            data.setdefault("source", self.origin)
        return data


def _split_list(value: str) -> list[str]:
    value = value.replace("\u2022", "-")
    if "\n" in value:
        parts = [part.strip(" -*\t") for part in value.splitlines()]
    else:
        parts = [part.strip() for part in re.split(r"[,;]", value)]
    return [part for part in parts if part]


def parse_document(text: str, *, origin: str | None = None) -> list[dict[str, object]]:
    text = _strip_bom(text)
    sections = [section.strip() for section in SPLIT_RE.split(text) if section.strip()]
    if not sections:
        sections = [text]

    results: list[dict[str, object]] = []
    for section in sections:
        product = RawProduct(origin=origin)
        current_key: str | None = None
        buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal buffer, current_key
            if current_key and buffer:
                product.merge_multiline(current_key, buffer)
            buffer = []

        for line in _to_lines(section):
            if not line.strip() and buffer:
                buffer.append("")
                continue
            match = KEY_VALUE_RE.match(line)
            if match:
                flush_buffer()
                key = _normalize_key(match.group(1))
                value = match.group(2).strip()
                if key:
                    current_key = key
                    if value:
                        product.set_value(key, value)
                        buffer = []
                    else:
                        buffer = []
                else:
                    buffer.append(line)
                continue
            if current_key:
                buffer.append(line)
            elif line.strip():
                # treat as title hint if title not set yet
                existing = product.fields.get("title")
                if existing:
                    buffer.append(line)
                else:
                    product.fields["title"] = line.strip()

        flush_buffer()
        data = product.as_dict()
        if any(field in data for field in ("id", "title", "buy_url")):
            results.append(data)

    return results


TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _transliterate(value: str) -> str:
    return "".join(TRANSLIT_MAP.get(ch, TRANSLIT_MAP.get(ch.lower(), ch)) for ch in value)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = _transliterate(value)
    value = value.replace("ё", "е")
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    stripped = re.sub(r"[^a-z0-9]+", "-", stripped)
    stripped = re.sub(r"-+", "-", stripped).strip("-")
    return stripped or "product"


def _slug_variants(value: str) -> list[str]:
    slug = _slugify(value)
    variants = {slug, slug.replace("-", ""), slug.replace("-", "_")}
    return [variant for variant in variants if variant]


def _load_schema() -> tuple[list[str], dict[str, str]]:
    if not SCHEMA_PATH.exists():
        return ["utm_source", "utm_medium", "utm_campaign", "utm_content"], {
            "utm_source": "tg_bot",
            "utm_medium": "catalog",
            "utm_campaign": "catalog",
            "utm_content": "{product_id}",
        }

    schema = json.loads(_read_text(SCHEMA_PATH))
    required = ["utm_source", "utm_medium", "utm_campaign", "utm_content"]
    defaults = {
        "utm_source": "tg_bot",
        "utm_medium": "catalog",
        "utm_campaign": "catalog",
        "utm_content": "{product_id}",
    }

    if isinstance(schema.get("x-required-utm"), list):
        required = [str(item) for item in schema["x-required-utm"] if str(item)]
    if isinstance(schema.get("x-default-utm"), dict):
        defaults = {str(key): str(value) for key, value in schema["x-default-utm"].items()}

    return required, defaults


REQUIRED_UTM, DEFAULT_UTM = _load_schema()


def _resolve_default_utm(product_id: str, category_slug: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, template in DEFAULT_UTM.items():
        if "{category}" in template:
            values[key] = template.format(
                product_id=product_id,
                product=product_id,
                category=category_slug or "catalog",
            )
        else:
            values[key] = template.format(product_id=product_id, product=product_id)
    if "utm_campaign" not in values or not values["utm_campaign"].strip():
        values["utm_campaign"] = category_slug or "catalog"
    values.setdefault("utm_content", product_id)
    return values


def _ensure_utm(url: str, *, required: Sequence[str], defaults: Mapping[str, str]) -> tuple[str, list[str]]:
    parsed = urlparse(url)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}

    missing: set[str] = set()
    changed = False

    for key in required:
        desired = defaults.get(key)
        if not desired:
            missing.add(key)
            continue
        if query.get(key) != desired:
            query[key] = desired
            changed = True

    for key, value in defaults.items():
        if key in required:
            continue
        if query.get(key) == value:
            continue
        query.setdefault(key, value)

    if changed:
        parsed = parsed._replace(query=urlencode(query, doseq=True))
        url = urlunparse(parsed)

    for key in required:
        if not query.get(key):
            missing.add(key)

    return url, sorted(missing)


def _github_api_from_raw(url: ParseResult) -> tuple[str, str] | None:
    parts = [part for part in url.path.split("/") if part]
    if len(parts) < 4:
        return None
    owner, repo, ref, *path_parts = parts
    path = "/".join(path_parts)
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1", path


def _github_api_from_tree(url: ParseResult) -> tuple[str, str] | None:
    parts = [part for part in url.path.split("/") if part]
    try:
        tree_index = parts.index("tree")
    except ValueError:
        return None
    owner = parts[0]
    repo = parts[1]
    ref = parts[tree_index + 1]
    path = "/".join(parts[tree_index + 2 :])
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1", path


def _list_remote_github_files(url: str) -> list[str]:
    parsed = urlparse(url)
    api_info: tuple[str, str] | None = None
    if parsed.netloc == "raw.githubusercontent.com":
        info = _github_api_from_raw(parsed)
        if info:
            api_info = info
    elif parsed.netloc == "github.com":
        info = _github_api_from_tree(parsed)
        if info:
            api_info = info

    if not api_info:
        raise CatalogBuildError(
            "Unable to list files for URL. Provide an explicit raw GitHub directory URL."
        )

    api_url, rel_path = api_info
    payload = json.loads(_http_get(api_url, accept="application/vnd.github+json").decode("utf-8"))
    if payload.get("truncated"):
        logging.warning("GitHub tree listing truncated for %s", url)
    entries = []
    prefix = rel_path.rstrip("/") + "/" if rel_path else ""
    for node in payload.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node.get("path")
        if not isinstance(path, str):
            continue
        if prefix and not path.startswith(prefix):
            continue
        if not path.lower().endswith(".txt"):
            continue
        entries.append(path)
    if not entries:
        raise CatalogBuildError(f"No description files found at {url}")
    entries.sort()
    base = "https://raw.githubusercontent.com"
    raw_parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "raw.githubusercontent.com":
        owner, repo, ref, *_ = raw_parts
    else:
        owner = raw_parts[0]
        repo = raw_parts[1]
        ref = raw_parts[3]
    downloads = [f"{base}/{owner}/{repo}/{ref}/{path}" for path in entries]
    return downloads


def _load_description_sources(url_or_path: str | None) -> list[tuple[str, str]]:
    if not url_or_path:
        url_or_path = DEFAULT_DESCRIPTIONS_URL

    if _looks_like_url(url_or_path):
        if url_or_path.lower().endswith(".txt"):
            text = _http_get(url_or_path).decode("utf-8")
            return [(url_or_path, text)]
        urls = _list_remote_github_files(url_or_path)
        return [(raw_url, _http_get(raw_url).decode("utf-8")) for raw_url in urls]

    path = Path(url_or_path)
    if path.is_file():
        return [(str(path), _read_text(path))]
    if path.is_dir():
        texts = []
        for file in sorted(path.glob("**/*.txt")):
            texts.append((str(file), _read_text(file)))
        if not texts:
            raise CatalogBuildError(f"No .txt files found in {path}")
        return texts
    raise CatalogBuildError(f"Unknown descriptions source {url_or_path}")


def _list_local_images(path: Path) -> list[str]:
    return sorted(
        str(file.relative_to(path)).replace(os.sep, "/")
        for file in path.rglob("*")
        if file.is_file() and file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def _load_image_index(images_base: str) -> tuple[str, list[str]]:
    if _looks_like_url(images_base):
        parsed = urlparse(images_base)
        if parsed.netloc != "raw.githubusercontent.com":
            raise CatalogBuildError("Image base must point to raw.githubusercontent.com for remote builds")
        api_info = _github_api_from_raw(parsed)
        if not api_info:
            raise CatalogBuildError("Unable to build GitHub API URL for images base")
        api_url, rel_path = api_info
        payload = json.loads(
            _http_get(api_url, accept="application/vnd.github+json").decode("utf-8")
        )
        entries: list[str] = []
        prefix = rel_path.rstrip("/") + "/" if rel_path else ""
        for node in payload.get("tree", []):
            if node.get("type") != "blob":
                continue
            path = node.get("path")
            if not isinstance(path, str):
                continue
            if prefix and not path.startswith(prefix):
                continue
            if Path(path).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            entries.append(path)
        if not entries:
            raise CatalogBuildError(f"No images discovered for {images_base}")
        entries.sort()
        owner, repo, ref, *_ = [part for part in parsed.path.split("/") if part]
        base = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}"
        return base.rstrip("/"), entries

    path = Path(images_base)
    if not path.exists():
        raise CatalogBuildError(f"Images path {images_base} does not exist")
    entries = _list_local_images(path)
    if not entries:
        raise CatalogBuildError(f"No image files found under {images_base}")
    return path.as_posix().rstrip("/"), entries


def _stem_variants(stem: str) -> list[str]:
    variants = {stem}
    for suffix in ("_main", "-main", "_01", "-01", "_1", "-1"):
        if stem.endswith(suffix):
            variants.add(stem[: -len(suffix)])
    variants.add(stem.replace("_", "-"))
    variants.add(stem.replace("-", "_"))
    return [variant for variant in variants if variant]


def _build_image_lookup(files: Sequence[str]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    for file in files:
        name = Path(file).name
        stem = Path(file).stem.lower()
        variants = set(_stem_variants(stem))
        variants.add(_slugify(stem))
        for variant in variants:
            lookup.setdefault(variant, []).append(file)
    for paths in lookup.values():
        paths.sort()
    return lookup


def _select_image(slug: str, lookup: Mapping[str, Sequence[str]]) -> str | None:
    variants = [slug] + _slug_variants(slug)
    seen: set[str] = set()
    candidates: list[str] = []
    for variant in variants:
        for key in {variant, variant.replace("-", "_"), variant.replace("_", "-")}:
            for path in lookup.get(key, []):
                if path not in seen:
                    candidates.append(path)
                    seen.add(path)

    if not candidates:
        return None

    def weight(path: str) -> tuple[int, str]:
        name = Path(path).stem
        if name.endswith("_main"):
            return (0, path)
        if name.endswith("-main"):
            return (0, path)
        if name.endswith("_01") or name.endswith("-01"):
            return (1, path)
        return (2, path)

    candidates.sort(key=weight)
    return candidates[0]


def _normalize_tags(value: object) -> list[str] | None:
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or None
    if isinstance(value, str):
        items = _split_list(value)
        return items or None
    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"false", "нет", "no", "0"}:
            return False
        if lowered in {"true", "да", "yes", "1"}:
            return True
    return None


def _normalize_product(raw: Mapping[str, object], *, images: Mapping[str, Sequence[str]], images_base: str) -> dict[str, object]:
    title = str(raw.get("title") or raw.get("name") or "").strip()
    if not title:
        raise CatalogBuildError("Product title is missing")
    product_id = str(raw.get("id") or _slugify(title)).strip()
    slug = _slugify(product_id)

    short = str(raw.get("short") or "").strip()
    description = str(raw.get("description") or "").strip()
    usage = str(raw.get("usage") or raw.get("recommendations") or "").strip()
    contra = str(raw.get("contra") or raw.get("warnings") or "").strip()
    category = str(raw.get("category") or "").strip()
    category_slug = _slugify(category) if category else "catalog"

    buy_url = str(raw.get("buy_url") or raw.get("order_url") or "").strip()
    if not buy_url:
        raise CatalogBuildError(f"{product_id}: missing buy URL")

    tags = _normalize_tags(raw.get("tags")) or []
    aliases = _normalize_tags(raw.get("aliases")) or []

    available_flag = _coerce_bool(raw.get("available"))

    defaults = _resolve_default_utm(slug, category_slug)
    defaults.setdefault("utm_campaign", category_slug)
    defaults.setdefault("utm_content", slug)
    buy_url, missing = _ensure_utm(buy_url, required=REQUIRED_UTM, defaults=defaults)
    if missing:
        raise CatalogBuildError(f"{product_id}: missing utm parameters {missing}")

    image_path = _select_image(slug, images)
    images_list: list[str] = []
    if image_path:
        full_url = images_base.rstrip("/") + "/" + quote(image_path, safe="/")
        images_list.append(full_url)
        available = True if available_flag is None else available_flag
    else:
        logging.warning("Image not found for %s", title)
        available = False if available_flag is None else available_flag

    product: dict[str, object] = {
        "id": product_id,
        "code": product_id,
        "title": title,
        "name": title,
        "order": {"velavie_link": buy_url},
    }

    if short:
        product["short"] = short
    if description:
        product["description"] = description
    if usage:
        product["usage"] = usage
    if contra:
        product["contra"] = contra
    if category:
        product["category"] = category
    if tags:
        product["tags"] = tags
    if aliases:
        product["aliases"] = aliases
    if images_list:
        product["image"] = images_list[0]
        product["images"] = images_list
    if available is not None:
        product["available"] = available

    for key in ("composition", "benefits"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            product[key] = value.strip()

    return product


def build_catalog(*, descriptions_url: str | None, images_base: str | None, output: Path | None) -> tuple[int, Path]:
    sources = _load_description_sources(descriptions_url)
    entries: list[dict[str, object]] = []
    for origin, text in sources:
        for record in parse_document(text, origin=origin):
            record.setdefault("origin", origin)
            entries.append(record)

    if not entries:
        raise CatalogBuildError("No products found in descriptions")

    images_base = images_base or DEFAULT_IMAGES_BASE
    base, files = _load_image_index(images_base)
    image_lookup = _build_image_lookup(files)

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in entries:
        product = _normalize_product(record, images=image_lookup, images_base=base)
        product_id = product["id"]
        if product_id in seen:
            logging.warning("Duplicate product id %s encountered; keeping first", product_id)
            continue
        seen.add(product_id)
        normalized.append(product)

    if not normalized:
        raise CatalogBuildError("No valid product entries found")

    normalized.sort(key=lambda item: _slugify(str(item.get("title", ""))))

    destination = output or CATALOG_PATH
    payload = {"products": normalized}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return len(normalized), destination


def validate_catalog(path: Path | None = None) -> int:
    path = path or CATALOG_PATH
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced as CatalogBuildError
        raise CatalogBuildError(f"Catalog file {path} is not valid JSON") from exc

    if not isinstance(data, dict) or "products" not in data:
        raise CatalogBuildError("Catalog must be a JSON object with a 'products' array")

    products = data.get("products")
    if not isinstance(products, list) or not products:
        raise CatalogBuildError("Catalog must contain at least one product")

    seen: set[str] = set()
    for item in products:
        if not isinstance(item, dict):
            raise CatalogBuildError("Catalog contains a non-object product entry")
        product_id = str(item.get("id") or "").strip()
        if not product_id:
            raise CatalogBuildError("Catalog product is missing id")
        if product_id in seen:
            raise CatalogBuildError(f"Duplicate product id {product_id}")
        seen.add(product_id)
        order = item.get("order")
        if not isinstance(order, dict) or not order.get("velavie_link"):
            raise CatalogBuildError(f"{product_id}: missing order.velavie_link")
        link = str(order["velavie_link"])
        parsed = urlparse(link)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        for key in REQUIRED_UTM:
            if key not in query or not query[key]:
                raise CatalogBuildError(f"{product_id}: missing {key} utm parameter")

    return len(products)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the catalog products file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Fetch descriptions and build the catalog")
    build_parser.add_argument("--descriptions-url", dest="descriptions_url", default=None, help="Descriptions source (file, dir or URL)")
    build_parser.add_argument("--images-base", dest="images_base", default=None, help="Base URL or directory containing product images")
    build_parser.add_argument("--output", type=Path, default=None, help="Output catalog path (defaults to app/catalog/products.json)")

    validate_parser = subparsers.add_parser("validate", help="Validate an existing catalog file")
    validate_parser.add_argument("--source", type=Path, default=CATALOG_PATH, help="Path to catalog JSON file")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        if args.command == "build":
            count, path = build_catalog(
                descriptions_url=args.descriptions_url,
                images_base=args.images_base,
                output=args.output,
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

