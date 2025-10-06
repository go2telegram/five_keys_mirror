"""Catalog package: loader and handlers for product catalog."""

from .loader import CatalogData, Category, Product, get_catalog, load_products

__all__ = [
    "CatalogData",
    "Category",
    "Product",
    "get_catalog",
    "load_products",
]
