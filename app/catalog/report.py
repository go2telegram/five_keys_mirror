"""Catalog summary and reporting utilities."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .loader import CatalogError, load_catalog


@dataclass(frozen=True)
class CatalogSummary:
    """Aggregated catalog statistics for reporting."""

    total: int
    available: int
    with_goals: int
    missing_images: int
    missing_order: int
    categories: dict[str, int]

    def format(self) -> str:
        """Render the summary as a human-readable multi-line string."""

        lines = [
            "📦 Catalog build summary",
            f"Всего продуктов: {self.total}",
            f"Доступны: {self.available}",
            f"С целями: {self.with_goals}",
            f"Без изображения: {self.missing_images}",
            f"Без ссылки заказа: {self.missing_order}",
        ]
        if self.categories:
            lines.append("Категории:")
            for name, count in sorted(
                self.categories.items(), key=lambda item: (-item[1], item[0])
            ):
                lines.append(f"• {name}: {count}")
        return "\n".join(lines)


def _iter_products(products: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for product in products:
        if isinstance(product, dict) and product.get("id"):
            normalized.append(product)
    return normalized


def summarize_products(products: Iterable[dict[str, Any]]) -> CatalogSummary:
    """Build aggregated statistics from catalog product dictionaries."""

    items = _iter_products(products)
    if not items:
        raise CatalogError("Catalog must contain at least one product")

    total = len(items)
    available = 0
    with_goals = 0
    missing_images = 0
    missing_order = 0
    categories: Counter[str] = Counter()

    for product in items:
        if product.get("available", True):
            available += 1

        goals = product.get("goals")
        if isinstance(goals, list) and any(str(goal).strip() for goal in goals):
            with_goals += 1

        image = product.get("image")
        images = product.get("images")
        has_image = False
        if isinstance(images, list):
            for value in images:
                if isinstance(value, str) and value.strip():
                    has_image = True
                    break
        if not has_image and isinstance(image, str) and image.strip():
            has_image = True
        if not has_image:
            missing_images += 1

        order = product.get("order")
        velavie_link = None
        if isinstance(order, dict):
            velavie_link = order.get("velavie_link")
        if not isinstance(velavie_link, str) or not velavie_link.strip():
            missing_order += 1

        category = product.get("category")
        if isinstance(category, str) and category.strip():
            categories[category.strip()] += 1
        else:
            categories["(uncategorized)"] += 1

    return CatalogSummary(
        total=total,
        available=available,
        with_goals=with_goals,
        missing_images=missing_images,
        missing_order=missing_order,
        categories=dict(categories),
    )


def build_catalog_summary(*, refresh: bool = False) -> CatalogSummary:
    """Load the catalog from disk and build its summary."""

    data = load_catalog(refresh=refresh)
    ordered = data.get("ordered") or list(data.get("products", {}))
    products = [data["products"].get(pid) for pid in ordered]
    fallback = [
        product
        for pid, product in data.get("products", {}).items()
        if pid not in ordered
    ]
    return summarize_products([item for item in products + fallback if item])


def build_catalog_summary_from_payload(payload: dict[str, Any]) -> CatalogSummary:
    """Create a summary from a JSON payload loaded from products.json."""

    products = payload.get("products")
    if not isinstance(products, list):
        raise CatalogError("Catalog JSON must contain a 'products' array")
    return summarize_products(product for product in products if isinstance(product, dict))


def build_catalog_summary_from_file(path: Path) -> CatalogSummary:
    """Read products.json from disk and return its summary."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced to caller
        raise CatalogError(f"Cannot read catalog file {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced to caller
        raise CatalogError(f"Catalog file {path} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CatalogError("Catalog JSON must contain an object at the top level")
    return build_catalog_summary_from_payload(payload)


__all__ = [
    "CatalogSummary",
    "build_catalog_summary",
    "build_catalog_summary_from_file",
    "build_catalog_summary_from_payload",
    "summarize_products",
]
