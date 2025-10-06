"""Catalog loader with schema validation and in-memory cache."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from pydantic import BaseModel, Field, HttpUrl, ValidationError, model_validator

LOGGER = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "products.json"


class Product(BaseModel):
    """Single catalog product entry."""

    id: str
    name: str
    short: str
    description: str
    image: HttpUrl
    buy_url: HttpUrl
    tags: List[str] = Field(default_factory=list)


class Category(BaseModel):
    """Catalog category with product references."""

    id: str
    title: str
    description: str | None = None
    product_ids: List[str] = Field(default_factory=list)


class CatalogSchema(BaseModel):
    """Raw schema loaded from JSON."""

    categories: List[Category]
    products: List[Product]

    @model_validator(mode="after")
    def _check_integrity(self) -> "CatalogSchema":
        product_ids = {product.id for product in self.products}
        if len(product_ids) != len(self.products):
            raise ValueError("duplicate product ids in catalog")

        category_ids = {category.id for category in self.categories}
        if len(category_ids) != len(self.categories):
            raise ValueError("duplicate category ids in catalog")

        for category in self.categories:
            missing = [pid for pid in category.product_ids if pid not in product_ids]
            if missing:
                raise ValueError(
                    f"category '{category.id}' references unknown products: {', '.join(missing)}"
                )

        assigned_products = {pid for category in self.categories for pid in category.product_ids}
        orphans = [pid for pid in product_ids if pid not in assigned_products]
        if orphans:
            raise ValueError(
                "products missing in any category: " + ", ".join(sorted(orphans))
            )
        return self


@dataclass(slots=True)
class CatalogData:
    """Processed catalog ready for runtime use."""

    categories: Dict[str, Category]
    products: Dict[str, Product]
    categories_order: List[str]
    category_products: Dict[str, List[Product]]
    product_categories: Dict[str, List[str]]

    def iter_categories(self) -> Iterable[Category]:
        """Iterate categories respecting the configured order."""

        for category_id in self.categories_order:
            category = self.categories.get(category_id)
            if category:
                yield category


_catalog_cache: CatalogData | None = None
_catalog_digest: str | None = None


def _build_catalog(schema: CatalogSchema) -> CatalogData:
    categories = {category.id: category for category in schema.categories}
    products = {product.id: product for product in schema.products}

    category_products: Dict[str, List[Product]] = {}
    product_categories: Dict[str, List[str]] = {pid: [] for pid in products}

    for category in schema.categories:
        category_products[category.id] = [products[pid] for pid in category.product_ids]
        for pid in category.product_ids:
            product_categories[pid].append(category.id)

    return CatalogData(
        categories=categories,
        products=products,
        categories_order=[category.id for category in schema.categories],
        category_products=category_products,
        product_categories=product_categories,
    )


def load_products(*, force: bool = False, path: Path | None = None) -> CatalogData:
    """Load products from JSON with validation and caching."""

    global _catalog_cache, _catalog_digest

    target_path = path or DATA_PATH
    raw = target_path.read_text("utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    if not force and _catalog_cache is not None and digest == _catalog_digest:
        return _catalog_cache

    try:
        payload = json.loads(raw)
        schema = CatalogSchema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        LOGGER.error("Failed to load catalog: %s", exc)
        raise

    _catalog_cache = _build_catalog(schema)
    _catalog_digest = digest

    LOGGER.info(
        "Catalog loaded: %d categories, %d products",
        len(_catalog_cache.categories),
        len(_catalog_cache.products),
    )
    return _catalog_cache


def get_catalog() -> CatalogData:
    """Return cached catalog, loading it if needed."""

    global _catalog_cache

    if _catalog_cache is None:
        _catalog_cache = load_products()
    return _catalog_cache
