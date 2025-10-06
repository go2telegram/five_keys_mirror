"""Helpers for catalog management, analytics and admin tools."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from app.catalog import analytics
from app.products import (
    BUY_URLS,
    CATALOG_PATH,
    GOAL_MAP,
    PRODUCTS,
    get_product,
    get_product_categories,
    reload_products,
)
from app.storage import save_event


def reload_catalog() -> Tuple[Path, int]:
    """Reload products.json and return path + count."""
    return reload_products()


def get_catalog_path() -> Path | None:
    return CATALOG_PATH


def get_product_info(code: str) -> dict | None:
    return get_product(code)


def get_buy_url(code: str) -> str | None:
    return BUY_URLS.get(code)


def record_view(user_id: int | None, source: str | None, product_ids: Iterable[str], campaign: str) -> None:
    campaign_norm = analytics.normalize_campaign(campaign)
    analytics.record_view(product_ids, campaign_norm)
    if user_id is None:
        return
    for pid in product_ids:
        save_event(user_id, source, "catalog_view", {"product_id": pid, "campaign": campaign_norm})


def record_click(user_id: int | None, source: str | None, product_id: str, campaign: str) -> None:
    campaign_norm = analytics.normalize_campaign(campaign)
    analytics.record_click(product_id, campaign_norm)
    if user_id is None:
        return
    save_event(user_id, source, "catalog_click", {"product_id": product_id, "campaign": campaign_norm})


def get_stats() -> dict:
    return analytics.get_stats()


__all__ = [
    "reload_catalog",
    "get_catalog_path",
    "get_product_info",
    "get_buy_url",
    "get_product_categories",
    "record_view",
    "record_click",
    "get_stats",
    "GOAL_MAP",
    "PRODUCTS",
    "BUY_URLS",
]
