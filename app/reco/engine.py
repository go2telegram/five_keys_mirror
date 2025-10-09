"""Rule-based recommendation helpers for AI plan scaffolding."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.catalog.loader import load_catalog

_CATEGORIES_PATH = Path(__file__).with_name("categories.yaml")
_DEFAULT_UTM = "ai_plan"


def _normalize_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(tag) for tag in raw if tag]
    if isinstance(raw, (set, tuple)):
        return [str(tag) for tag in raw if tag]
    if isinstance(raw, str) and raw:
        return [raw]
    return []


@lru_cache(maxsize=1)
def _load_categories() -> dict[str, dict[str, Any]]:
    try:
        with _CATEGORIES_PATH.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}

    categories: dict[str, dict[str, Any]] = {}
    if isinstance(payload, dict):
        for name, meta in payload.items():
            if not isinstance(meta, dict):
                continue
            category_tags = _normalize_tags(meta.get("tags"))
            categories[str(name)] = {
                "utm_category": str(meta.get("utm_category") or name),
                "tags": {tag.lower() for tag in category_tags},
            }
    return categories


def _resolve_utm(product: dict[str, Any]) -> str:
    categories = _load_categories()
    product_tags = {tag.lower() for tag in _normalize_tags(product.get("tags"))}
    product_category = str(product.get("category") or "").lower()

    for name, meta in categories.items():
        tag_hits = product_tags.intersection(meta.get("tags", set()))
        if tag_hits:
            return meta.get("utm_category", name) or _DEFAULT_UTM
        if product_category and product_category == name.lower():
            return meta.get("utm_category", name) or _DEFAULT_UTM
    return _DEFAULT_UTM


def _short_reason(product: dict[str, Any]) -> str:
    short = product.get("short")
    if isinstance(short, str) and short.strip():
        return short.strip()
    description = product.get("description")
    if isinstance(description, str) and description.strip():
        first_sentence = description.strip().split(".")[0]
        return first_sentence.strip()
    return ""


async def get_reco(user_id: int, limit: int = 5, verbose: bool = False) -> list[dict[str, Any]]:
    """Return top-N catalog items with metadata for AI planning."""

    if limit <= 0:
        return []

    catalog = load_catalog()
    ordered_ids = catalog.get("ordered") or []
    products = catalog.get("products") or {}

    items: list[dict[str, Any]] = []
    for pid in ordered_ids:
        product = products.get(pid)
        if not isinstance(product, dict):
            continue
        title = product.get("title") or product.get("name") or pid
        order_info = product.get("order") or {}
        record = {
            "id": pid,
            "title": str(title),
            "utm_category": _resolve_utm(product),
            "why": _short_reason(product),
            "tags": _normalize_tags(product.get("tags")),
            "buy_url": order_info.get("velavie_link") or order_info.get("url"),
        }
        items.append(record)
        if len(items) >= limit:
            break

    return items


__all__ = ["get_reco"]
