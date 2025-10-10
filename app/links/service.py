"""Convenience helpers for accessing link snapshot data."""

from __future__ import annotations

from typing import Dict

from app.config import settings
from .storage import LinkSnapshot, load_snapshot


def get_register_url(*, refresh: bool = False) -> str | None:
    """Return the preferred registration link with settings fallback."""

    snapshot = load_snapshot(refresh=refresh)
    if snapshot.register_url:
        return snapshot.register_url
    return settings.velavie_url


def get_product_links_map(*, refresh: bool = False) -> Dict[str, str]:
    """Return a copy of product link overrides."""

    snapshot = load_snapshot(refresh=refresh)
    return dict(snapshot.products)


__all__ = ["get_register_url", "get_product_links_map", "LinkSnapshot"]
