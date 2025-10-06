"""Metrics helpers namespace."""

from .product import log_catalog_search, log_product_click_buy, log_product_view

__all__ = [
    "log_catalog_search",
    "log_product_click_buy",
    "log_product_view",
]
