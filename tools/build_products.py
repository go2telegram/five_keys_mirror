#!/usr/bin/env python3
"""Build products catalog from description file and media assets."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import ProxyHandler, Request, build_opener

try:  # pragma: no cover - optional dependency
    import requests  # type: ignore
except ImportError:  # pragma: no cover - fallback to urllib
    requests = None  # type: ignore[assignment]

DEFAULT_MEDIA_BASE_URL = os.environ.get(
    "MEDIA_BASE_URL",
    "https://raw.githubusercontent.com/go2telegram/media/main",
)
DEFAULT_DESCRIPTION_FILENAME = "Полное описание продуктов vilavi (оформлено v3).txt"
DEFAULT_DESCRIPTIONS_URL = os.environ.get(
    "DESCRIPTIONS_URL",
    f"{DEFAULT_MEDIA_BASE_URL}/media/descriptions/{quote(DEFAULT_DESCRIPTION_FILENAME)}",
)
DEFAULT_MEDIA_PRODUCTS_API = os.environ.get(
    "MEDIA_PRODUCTS_API",
    "https://api.github.com/repos/go2telegram/media/contents/media/products",
)
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".webp", ".png"}
TMP_DIR = Path(os.getenv("TMPDIR", "/tmp")) / "catalog_build"
TMP_DIR.mkdir(parents=True, exist_ok=True)
FIELD_ALIASES: Dict[str, str] = {
    "id": "id",
    "code": "id",
    "name": "name",
    "title": "name",
    "short": "short",
    "short description": "short",
    "description": "description",
    "usage": "usage",
    "how to use": "usage",
    "contra": "contra",
    "contraindications": "contra",
    "buy url": "buy_url",
    "buy link": "buy_url",
    "url": "buy_url",
    "category": "category",
    "tags": "tags",
    "tag": "tags",
    "image": "image",
    "image file": "image",
}
MULTILINE_FIELDS = {"short", "description", "usage", "contra"}
LIST_FIELDS = {"tags"}
REQUIRED_FIELDS = [
    "id",
    "name",
    "short",
    "description",
    "usage",
    "contra",
    "buy_url",
    "category",
]


class CatalogBuilderError(RuntimeError):
    """Custom exception for catalog builder errors."""


def _normalize_newlines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _cleanup_multiline(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def _parse_tags(raw: str | Iterable[str]) -> List[str]:
    if isinstance(raw, str):
        parts = re.split(r"[;,]", raw)
    else:
        parts = list(raw)
    return [p.strip() for p in parts if p and p.strip()]


REQUEST_TIMEOUT = float(os.environ.get("CATALOG_REQUEST_TIMEOUT", "30"))
_URL_OPENER = build_opener(ProxyHandler({}))


def _make_headers(for_api: bool = False) -> Dict[str, str]:
    headers: Dict[str, str] = {"User-Agent": "catalog-builder/1.0"}
    if for_api:
        headers["Accept"] = "application/vnd.github.v3+json"
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get(url: str, headers: Dict[str, str]) -> tuple[int, str]:
    if requests is not None:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                proxies={},
            )
        except Exception as exc:  # pragma: no cover - network failure
            raise CatalogBuilderError(f"Failed to query {url}: {exc}") from exc
        return response.status_code, response.text

    req = Request(url, headers=headers)
    try:
        with _URL_OPENER.open(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read()
            text = body.decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
            return status, text
    except HTTPError as exc:  # pragma: no cover - network failure
        body = exc.read()
        text = body.decode("utf-8", errors="replace")
        return exc.code, text
    except URLError as exc:  # pragma: no cover - network failure
        raise CatalogBuilderError(f"Failed to query {url}: {exc}") from exc


def fetch_remote_text(url: str) -> str:
    status, text = _http_get(url, _make_headers())
    if status >= 400:
        snippet = text.strip().splitlines()
        detail = f" {snippet[0][:200]}" if snippet else ""
        raise CatalogBuilderError(
            f"Failed to download descriptions from {url}: HTTP {status}{detail}"
        )
    return text


def _fetch_remote_json(url: str) -> Any:
    status, text = _http_get(url, _make_headers(for_api=True))
    if status >= 400:
        snippet = text.strip().splitlines()
        detail = f" {snippet[0][:200]}" if snippet else ""
        raise CatalogBuilderError(
            f"Failed to query {url}: HTTP {status}{detail}"
        )
    try:
        return json.loads(text)
    except ValueError as exc:  # pragma: no cover - invalid JSON
        raise CatalogBuilderError(f"Invalid JSON response from {url}: {exc}") from exc


def parse_description_text(text: str, source_name: str) -> List[Dict[str, Any]]:
    text = _normalize_newlines(text.lstrip("\ufeff"))
    lines = text.split("\n")

    products: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    current_field: str | None = None

    def finalize_current() -> None:
        nonlocal current, current_field
        if not current:
            return
        for field in REQUIRED_FIELDS:
            if not current.get(field):
                raise CatalogBuilderError(
                    "Missing required field '{field}' for product {pid!r} in {source}".format(
                        field=field,
                        pid=current.get("id"),
                        source=source_name,
                    )
                )
        if "tags" in current:
            current["tags"] = _parse_tags(current["tags"])
        else:
            current["tags"] = []

        for key, value in list(current.items()):
            if isinstance(value, str):
                cleaned = (
                    _cleanup_multiline(value)
                    if key in MULTILINE_FIELDS
                    else value.strip()
                )
                current[key] = cleaned

        products.append(current)
        current = {}
        current_field = None

    last_recognized_field: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip("\ufeff")
        stripped = line.strip()
        if not stripped:
            if current_field and current.get(current_field):
                current[current_field] += "\n"
            continue
        if stripped == "---":
            finalize_current()
            continue

        match = re.match(r"^([^:]+):\s*(.*)$", line)
        if match:
            key_raw = match.group(1).strip().lower()
            value = match.group(2)
            field = FIELD_ALIASES.get(key_raw)
            if field:
                if field not in current:
                    current[field] = ""
                if field in LIST_FIELDS:
                    current[field] = value
                    current_field = None
                else:
                    current[field] = value
                    current_field = field if field in MULTILINE_FIELDS else None
                last_recognized_field = field
                continue

        if current_field:
            current[current_field] += ("\n" if current[current_field] else "") + line.strip()
            continue
        if last_recognized_field and last_recognized_field in MULTILINE_FIELDS:
            current[last_recognized_field] += (
                ("\n" if current[last_recognized_field] else "") + line.strip()
            )
            current_field = last_recognized_field
            continue
        raise CatalogBuilderError(f"Unexpected line in description file: {line!r}")

    finalize_current()
    if not products:
        raise CatalogBuilderError(f"No products parsed from {source_name}")
    return products


def load_description_source(
    descriptions_dir: Path | None,
    description_file: str | None,
    descriptions_url: str | None,
) -> tuple[str, str]:
    if descriptions_url:
        parsed = urlparse(descriptions_url)
        if parsed.scheme in {"", "file"} and not parsed.netloc:
            candidate = Path(parsed.path) if parsed.scheme == "file" else Path(descriptions_url)
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            if candidate.exists():
                return candidate.read_text(encoding="utf-8-sig"), str(candidate)
            raise CatalogBuilderError(f"Description file {candidate} not found")

        text = fetch_remote_text(descriptions_url)
        name = Path(parsed.path).name or "descriptions.txt"
        tmp_file = TMP_DIR / name
        tmp_file.write_text(text, encoding="utf-8")
        return text, descriptions_url

    if description_file:
        candidate = Path(description_file)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8-sig"), str(candidate)
        if descriptions_dir:
            candidate = descriptions_dir / description_file
            if candidate.exists():
                return candidate.read_text(encoding="utf-8-sig"), str(candidate)
        raise CatalogBuilderError(f"Description file {description_file} not found")

    if descriptions_dir and descriptions_dir.exists():
        path = find_description_file(descriptions_dir)
        return path.read_text(encoding="utf-8-sig"), str(path)

    raise CatalogBuilderError(
        "Description source not found. Provide --descriptions-url or ensure descriptions directory exists."
    )


def _build_image_map_from_dir(products_dir: Path) -> Dict[str, str]:
    if not products_dir.exists():
        raise CatalogBuilderError(f"Images directory not found: {products_dir}")
    image_map: Dict[str, str] = {}
    priority = {".webp": 0, ".jpg": 1, ".jpeg": 1, ".png": 2}
    for path in sorted(products_dir.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        stem = path.stem.lower()
        current = image_map.get(stem)
        if current is None or priority.get(ext, 10) < priority.get(Path(current).suffix.lower(), 10):
            image_map[stem] = path.name
    if not image_map:
        raise CatalogBuilderError(f"No images found in {products_dir}")
    return image_map


def _build_image_map_from_api(api_url: str) -> Dict[str, str]:
    priority = {".webp": 0, ".jpg": 1, ".jpeg": 1, ".png": 2}
    image_map: Dict[str, str] = {}
    visited: set[str] = set()

    def walk(url: str) -> None:
        if url in visited:
            return
        visited.add(url)
        data = _fetch_remote_json(url)
        if not isinstance(data, list):
            raise CatalogBuilderError(f"Unexpected response from {url}: expected list of files")
        for entry in data:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            if entry_type == "file":
                name = entry.get("name")
                if not name:
                    continue
                ext = Path(name).suffix.lower()
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    continue
                stem = Path(name).stem.lower()
                current = image_map.get(stem)
                if (
                    current is None
                    or priority.get(ext, 10)
                    < priority.get(Path(current).suffix.lower(), 10)
                ):
                    image_map[stem] = name
            elif entry_type == "dir":
                sub_url = entry.get("url")
                if sub_url:
                    walk(sub_url)

    walk(api_url)
    if not image_map:
        raise CatalogBuilderError(f"No images found at {api_url}")
    return image_map


def build_image_map(
    products_dir: Path | None,
    media_products_api: str | None,
) -> Dict[str, str]:
    if products_dir and products_dir.exists():
        return _build_image_map_from_dir(products_dir)
    if media_products_api:
        return _build_image_map_from_api(media_products_api)
    raise CatalogBuilderError(
        "Images source not found. Provide --media-products-api or ensure products directory exists."
    )


def attach_images(
    products: List[Dict[str, Any]],
    image_map: Dict[str, str],
    media_base_url: str,
) -> None:
    base = media_base_url.rstrip("/")
    for product in products:
        image_key = product.get("image") or product["id"]
        if not isinstance(image_key, str):
            raise CatalogBuilderError(f"Invalid image key for product {product['id']}")
        image_name = image_map.get(image_key.lower())
        if not image_name:
            raise CatalogBuilderError(
                f"Image file for product {product['id']} not found (key={image_key})"
            )
        product["image"] = f"{base}/media/products/{image_name}"


def ensure_unique_ids(products: List[Dict[str, Any]]) -> None:
    seen: set[str] = set()
    for product in products:
        pid = product["id"]
        if pid in seen:
            raise CatalogBuilderError(f"Duplicate product id: {pid}")
        seen.add(pid)


def _is_valid_uri(value: str) -> bool:
    parts = urlparse(value)
    return bool(parts.scheme) and bool(parts.netloc)


def _format_path(path: Sequence[str | int]) -> str:
    if not path:
        return "<root>"
    return "/".join(str(p) for p in path)


def _validate_value(value: Any, schema: Dict[str, Any], path: Sequence[str | int], errors: List[str]) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{_format_path(path)}: expected object, got {type(value).__name__}")
            return
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        for field in required:
            if field not in value:
                errors.append(f"{_format_path(path + [field])}: field is required")
        for key, item in value.items():
            if key in properties:
                _validate_value(item, properties[key], path + [key], errors)
            elif additional is False:
                errors.append(f"{_format_path(path + [key])}: additional properties are not allowed")
    elif expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"{_format_path(path)}: expected array, got {type(value).__name__}")
            return
        if schema.get("uniqueItems"):
            seen_items = set()
            for item in value:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker in seen_items:
                    errors.append(f"{_format_path(path)}: array items must be unique")
                    break
                seen_items.add(marker)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_value(item, item_schema, path + [idx], errors)
    elif expected_type == "string":
        if not isinstance(value, str):
            errors.append(f"{_format_path(path)}: expected string, got {type(value).__name__}")
            return
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{_format_path(path)}: string is shorter than {min_length}")
        pattern = schema.get("pattern")
        if pattern and not re.match(pattern, value):
            errors.append(f"{_format_path(path)}: does not match pattern {pattern}")
        if schema.get("format") == "uri" and not _is_valid_uri(value):
            errors.append(f"{_format_path(path)}: invalid URI")
    elif expected_type is None:
        return
    else:
        # Unsupported types can be extended as needed
        if not isinstance(value, str):
            pass


def validate_products(products: Any, schema: Dict[str, Any]) -> None:
    errors: List[str] = []
    if schema.get("type") != "array":
        raise CatalogBuilderError("Schema root must describe an array")
    if not isinstance(products, list):
        raise CatalogBuilderError("Products data must be an array")

    if schema.get("uniqueItems"):
        seen = set()
        for idx, item in enumerate(products):
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if marker in seen:
                errors.append(f"{_format_path([idx])}: duplicate array item")
            seen.add(marker)

    item_schema = schema.get("items", {})
    for idx, item in enumerate(products):
        _validate_value(item, item_schema, [idx], errors)

    if errors:
        raise CatalogBuilderError("Schema validation failed:\n" + "\n".join(f"- {msg}" for msg in errors))


def find_description_file(descriptions_dir: Path, preferred: str | None = None) -> Path:
    if preferred:
        candidate = descriptions_dir / preferred
        if candidate.exists():
            return candidate
        candidate = Path(preferred)
        if candidate.exists():
            return candidate
        raise CatalogBuilderError(f"Description file {preferred} not found")

    if not descriptions_dir.exists():
        raise CatalogBuilderError(f"Descriptions directory not found: {descriptions_dir}")
    candidates = sorted(descriptions_dir.glob("*.txt"))
    if not candidates:
        raise CatalogBuilderError(
            f"No description files found in {descriptions_dir}"
        )
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return candidates[-1]


def load_schema(schema_path: Path) -> Dict[str, Any]:
    if not schema_path.exists():
        raise CatalogBuilderError(f"Schema file not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def build_catalog(
    descriptions_dir: Path | None,
    products_dir: Path | None,
    descriptions_url: str | None,
    output_path: Path,
    schema_path: Path,
    media_base_url: str,
    media_products_api: str | None,
    description_file: str | None = None,
) -> List[Dict[str, Any]]:
    text, source = load_description_source(descriptions_dir, description_file, descriptions_url)
    products = parse_description_text(text, source)
    image_map = build_image_map(products_dir, media_products_api)
    attach_images(products, image_map, media_base_url)
    ensure_unique_ids(products)
    products.sort(key=lambda item: item["id"])

    schema = load_schema(schema_path)
    validate_products(products, schema)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(products, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return products


def validate_catalog_file(output_path: Path, schema_path: Path) -> List[Dict[str, Any]]:
    if not output_path.exists():
        raise CatalogBuilderError(f"Catalog file not found: {output_path}")
    products = json.loads(output_path.read_text(encoding="utf-8"))
    schema = load_schema(schema_path)
    validate_products(products, schema)
    ensure_unique_ids(products)
    return products


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build products catalog")
    parser.add_argument(
        "--descriptions-dir",
        default=os.environ.get("DESCRIPTIONS_DIR"),
        help="Local directory with description txt files",
    )
    parser.add_argument(
        "--description-file",
        default=None,
        help="Specific description file name to use",
    )
    parser.add_argument(
        "--descriptions-url",
        default=DEFAULT_DESCRIPTIONS_URL,
        help="Direct URL to description txt file",
    )
    parser.add_argument(
        "--products-dir",
        default=os.environ.get("PRODUCTS_DIR"),
        help="Local directory with product images",
    )
    parser.add_argument(
        "--media-products-api",
        default=DEFAULT_MEDIA_PRODUCTS_API,
        help="API URL that lists product images (GitHub contents API)",
    )
    parser.add_argument(
        "--output",
        default="app/data/products.json",
        help="Path to write resulting JSON",
    )
    parser.add_argument(
        "--schema",
        default="app/data/products.schema.json",
        help="JSON schema path",
    )
    parser.add_argument(
        "--media-base-url",
        default=DEFAULT_MEDIA_BASE_URL,
        help="Base URL for media assets",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing catalog without rebuilding",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.validate_only:
            validate_catalog_file(Path(args.output), Path(args.schema))
        else:
            descriptions_dir = Path(args.descriptions_dir) if args.descriptions_dir else None
            products_dir = Path(args.products_dir) if args.products_dir else None
            build_catalog(
                descriptions_dir=descriptions_dir,
                products_dir=products_dir,
                descriptions_url=args.descriptions_url,
                output_path=Path(args.output),
                schema_path=Path(args.schema),
                media_base_url=args.media_base_url,
                media_products_api=args.media_products_api,
                description_file=args.description_file,
            )
    except CatalogBuilderError as exc:
        print(f"[build_products] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected errors
        print(f"[build_products] unexpected error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
