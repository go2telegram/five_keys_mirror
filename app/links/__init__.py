"""Utilities for managing partner and product links."""

from .storage import LinkSnapshot, load_snapshot, save_snapshot
from .service import get_register_url, get_product_links_map

__all__ = [
    "LinkSnapshot",
    "load_snapshot",
    "save_snapshot",
    "get_register_url",
    "get_product_links_map",
]
