#!/usr/bin/env python3
"""Utility helpers for building and validating product catalog data."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "app" / "catalog" / "products.json"
SCHEMA_PATH = ROOT / "app" / "data" / "products.schema.json"


class CatalogBuildError(RuntimeError):
    """Raised when catalog data cannot be normalized."""


def _load_schema() -> tuple[list[str], dict[str, str]]:
    required = ["utm_source", "utm_medium", "utm_campaign"]
    defaults: dict[str, str] = {
        "utm_source": "bot",
        "utm_medium": "telegram",
        "utm_campaign": "catalog",
        "utm_content": "{product_id}",
    }

    if not SCHEMA_PATH.exists():
        return required, defaults

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - should never happen
        raise CatalogBuildError(f"Schema {SCHEMA_PATH} is not valid JSON") from exc

    if isinstance(schema.get("x-required-utm"), list):
        required = [str(item) for item in schema["x-required-utm"] if str(item)]
    if isinstance(schema.get("x-default-utm"), dict):
        defaults = {str(key): str(value) for key, value in schema["x-default-utm"].items()}

    return required, defaults


REQUIRED_UTM, DEFAULT_UTM = _load_schema()


def _slugify(value: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "_" for ch in value.strip()]
    slug = "".join(cleaned).strip("_")
    return slug or "product"


def _resolve_defaults(product_id: str) -> dict[str, str]:
    slug = _slugify(product_id)
    resolved: dict[str, str] = {}
    for key, value in DEFAULT_UTM.items():
        if isinstance(value, str):
            resolved[key] = value.format(product_id=slug, product=slug)
        else:
            resolved[key] = str(value)
    return resolved


def _ensure_utm(
    url: str,
    *,
    required: Iterable[str],
    defaults: dict[str, str],
    overrides: dict[str, str] | None = None,
) -> Tuple[str, list[str]]:
    parsed = urlparse(url)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}

    overrides = overrides or {}
    applied = dict(defaults)
    for key, value in overrides.items():
        applied[key] = value

    missing: set[str] = set()
    changed = False

    for key in required:
        desired = applied.get(key)
        if not desired:
            missing.add(key)
            continue
        if query.get(key) != desired:
            query[key] = desired
            changed = True

    for key, value in overrides.items():
        if query.get(key) == value:
            continue
        query[key] = value
        changed = True

    for key, value in defaults.items():
        if key in required or key in overrides:
            continue
        if query.get(key) == value:
            continue
        query[key] = value
        changed = True

    if changed:
        parsed = parsed._replace(query=urlencode(query, doseq=True))
        url = urlunparse(parsed)

    for key in required:
        if not query.get(key):
            missing.add(key)

    return url, sorted(missing)


def _coerce_products(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        return [item for item in data["products"] if isinstance(item, dict)]
    if isinstance(data, dict):
        items: list[dict[str, Any]] = []
        for pid, meta in data.items():
            if not isinstance(meta, dict):
                continue
            copy = dict(meta)
            copy.setdefault("id", pid)
            items.append(copy)
        return items
    raise CatalogBuildError("products.json must contain an object or a products array")


def _normalize_product(item: dict[str, Any]) -> dict[str, Any]:
    product = dict(item)
    product_id = str(
        product.get("id")
        or product.get("code")
        or product.get("title")
        or product.get("name")
        or ""
    ).strip()
    if not product_id:
        raise CatalogBuildError("Product entry is missing id/title")

    product["id"] = product_id
    product.setdefault("code", product_id)
    if product.get("title"):
        product["title"] = str(product["title"])
    else:
        product["title"] = str(product.get("name") or product_id)

    aliases_raw = product.get("aliases")
    if isinstance(aliases_raw, (list, tuple, set)):
        product["aliases"] = [str(alias) for alias in aliases_raw if alias]
    elif aliases_raw in (None, ""):
        product.pop("aliases", None)
    else:
        product["aliases"] = [str(aliases_raw)]

    order_info: Dict[str, Any] = {}
    if isinstance(product.get("order"), dict):
        order_info = dict(product["order"])
    link = order_info.get("velavie_link") or product.pop("order_url", None) or product.pop("url", None)
    if not isinstance(link, str) or not link:
        raise CatalogBuildError(f"{product_id}: order URL is missing")

    overrides: dict[str, str] = {}
    raw_overrides = order_info.get("utm")
    if isinstance(raw_overrides, dict):
        overrides = {str(key): str(value) for key, value in raw_overrides.items() if value}
        order_info.pop("utm", None)

    defaults = _resolve_defaults(product_id)
    link, missing = _ensure_utm(link, required=REQUIRED_UTM, defaults=defaults, overrides=overrides)
    if missing:
        raise CatalogBuildError(f"{product_id}: missing utm parameters {missing}")

    order_info["velavie_link"] = link
    product["order"] = order_info

    return product


def _normalize_products(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in items:
        normalized_item = _normalize_product(product)
        product_id = normalized_item["id"]
        if product_id in seen:
            raise CatalogBuildError(f"Duplicate product id {product_id}")
        seen.add(product_id)
        normalized.append(normalized_item)
    return normalized


def build_catalog(source: Path, destination: Path | None = None) -> tuple[int, Path]:
    destination = destination or source
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CatalogBuildError(f"Source file {source} not found")
    except json.JSONDecodeError as exc:
        raise CatalogBuildError(f"Source file {source} is not valid JSON") from exc

    items = _coerce_products(data)
    normalized = _normalize_products(items)
    payload = {"products": normalized}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(normalized), destination


def validate_catalog(source: Path) -> int:
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CatalogBuildError(f"Source file {source} not found")
    except json.JSONDecodeError as exc:
        raise CatalogBuildError(f"Source file {source} is not valid JSON") from exc

    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise CatalogBuildError("products.json must contain a 'products' array")

    normalized = _normalize_products(data["products"])
    if normalized != data["products"]:
        raise CatalogBuildError("Catalog data is not normalized; run build-products")

    return len(normalized)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the catalog products file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Normalize the product catalog JSON")
    build_parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Source JSON file")
    build_parser.add_argument("--output", type=Path, default=None, help="Output file (defaults to --source)")

    validate_parser = subparsers.add_parser("validate", help="Validate the product catalog JSON")
    validate_parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Catalog JSON file")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    try:
        if args.command == "build":
            count, path = build_catalog(args.source, args.output)
            print(f"Normalized {count} products → {path}")
            return 0
        if args.command == "validate":
            count = validate_catalog(args.source)
            print(f"Catalog OK ({count} products)")
            return 0
    except CatalogBuildError as exc:
        print(f"ERROR: {exc}")
        return 1

    raise CatalogBuildError("Unknown command")


if __name__ == "__main__":  # pragma: no cover - CLI helper
    raise SystemExit(main())
