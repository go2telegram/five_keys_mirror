"""High-level catalog helpers with caching for hot paths."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List

from app.cache import catalog_cached
from app.catalog.loader import load_catalog
from app.db.session import session_scope
from app.products import GOAL_MAP
from app.storage import get_last_plan
from app.utils_media import precache_remote_images


def _normalize_product_payload(product: Dict[str, Any]) -> Dict[str, Any]:
    order = product.get("order") or {}
    return {
        "id": product.get("id"),
        "title": product.get("title") or product.get("name"),
        "short": product.get("short", ""),
        "order_url": order.get("velavie_link") or order.get("url"),
        "images": list(product.get("images") or []),
    }


@catalog_cached("catalog_search")
async def catalog_search(query: str) -> List[Dict[str, Any]]:
    if not query:
        return []
    catalog = load_catalog()
    products = catalog["products"]
    needle = query.strip().lower()
    if not needle:
        return []

    results: List[Dict[str, Any]] = []
    for product in products.values():
        haystack = " ".join(
            str(product.get(field, "")) for field in ("title", "name", "short") if product.get(field)
        ).lower()
        if needle in haystack:
            results.append(_normalize_product_payload(product))
        if len(results) >= 20:
            break
    if results:
        precache_remote_images(image for item in results for image in item.get("images", []) if isinstance(image, str))
    return results


@catalog_cached("product_get")
async def product_get(product_id: str) -> Dict[str, Any] | None:
    if not product_id:
        return None
    catalog = load_catalog()
    product = catalog["products"].get(product_id)
    if not product:
        return None
    payload = _normalize_product_payload(product)
    if payload:
        precache_remote_images(payload.get("images", []))
    return payload


async def _load_user_plan_products(user_id: int) -> List[str]:
    async with session_scope() as session:
        plan = await get_last_plan(session, user_id)
        if not plan:
            return []
        products = plan.get("products") or []
        return [str(code) for code in products if code]


_SLEEP_TAG_FALLBACKS: dict[str, list[str]] = {
    "magnesium": ["MAG_B6"],
    "glycine": ["MAG_B6"],
    "sleep_calm": ["OMEGA3"],
    "sleep_support": ["OMEGA3", "D3"],
    "mct": ["OMEGA3"],
}


def _fallback_reco(source: str | None, tags: Sequence[str] | None) -> list[str]:
    if source == "quiz:sleep":
        ordered: list[str] = []
        for tag in tags or []:
            for code in _SLEEP_TAG_FALLBACKS.get(tag, []):
                if code not in ordered:
                    ordered.append(code)
        for code in GOAL_MAP.get("sleep", []):
            if code not in ordered:
                ordered.append(code)
        return ordered
    return []


@catalog_cached("get_reco")
async def get_reco(
    user_id: int,
    *,
    limit: int = 3,
    source: str | None = None,
    tags: Sequence[str] | None = None,
) -> List[str]:
    products: list[str] = []
    if user_id:
        products = await _load_user_plan_products(user_id)
    if not products:
        products = _fallback_reco(source, tags)
    if limit and limit > 0:
        products = products[:limit]
    return products


__all__ = ["catalog_search", "product_get", "get_reco"]
