"""Business logic for partner link management."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.loader import load_catalog
from app.repo import link_sets as link_repo

_WHITESPACE_RE = re.compile(r"\s+")


class LinkValidationError(ValueError):
    """Raised when a partner URL fails validation."""


@dataclass(slots=True)
class ProductDescriptor:
    product_id: str
    title: str


def _catalog_products() -> List[ProductDescriptor]:
    catalog = load_catalog()
    products: Dict[str, Dict[str, Any]] = catalog.get("products", {})
    ordered: Iterable[str] = catalog.get("ordered") or products.keys()

    descriptors: List[ProductDescriptor] = []
    for pid in ordered:
        meta = products.get(pid, {})
        title = str(meta.get("title") or meta.get("name") or pid)
        descriptors.append(ProductDescriptor(product_id=pid, title=title))
    return descriptors


def allowed_product_ids() -> List[str]:
    return [item.product_id for item in _catalog_products()]


def _product_descriptor_map() -> Dict[str, ProductDescriptor]:
    return {item.product_id: item for item in _catalog_products()}


def validate_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if _WHITESPACE_RE.search(value):
        raise LinkValidationError("URL не должен содержать пробелов")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise LinkValidationError("URL должен начинаться с http:// или https://")
    if not parsed.netloc:
        raise LinkValidationError("URL должен содержать домен")
    if len(value) > 1024:
        raise LinkValidationError("URL слишком длинный")
    return value


async def list_sets_overview(session: AsyncSession) -> Dict[str, Any]:
    sets = await link_repo.list_sets(session)
    products = _catalog_products()
    active_id = next((item.id for item in sets if item.is_active), None)
    return {
        "sets": [
            {
                "id": item.id,
                "slug": item.slug,
                "title": item.title,
                "is_active": item.is_active,
            }
            for item in sets
        ],
        "active_set_id": active_id,
        "products": [
            {"id": descriptor.product_id, "title": descriptor.title} for descriptor in products
        ],
    }


async def load_set_details(session: AsyncSession, set_id: int) -> Dict[str, Any] | None:
    link_set = await link_repo.get_set(session, set_id)
    if link_set is None:
        return None

    products = _catalog_products()
    await link_repo.ensure_entries(session, link_set, (item.product_id for item in products))
    entries = await link_repo.load_entries_map(session, link_set.id)

    return {
        "id": link_set.id,
        "slug": link_set.slug,
        "title": link_set.title,
        "is_active": link_set.is_active,
        "registration_url": link_set.registration_url,
        "links": [
            {
                "product_id": descriptor.product_id,
                "title": descriptor.title,
                "url": entries.get(descriptor.product_id),
            }
            for descriptor in products
        ],
    }


async def activate_set(session: AsyncSession, set_id: int) -> Dict[str, Any] | None:
    link_set = await link_repo.set_active(session, set_id)
    if link_set is None:
        return None
    return {
        "id": link_set.id,
        "slug": link_set.slug,
        "title": link_set.title,
        "is_active": link_set.is_active,
    }


async def save_registration_url(session: AsyncSession, set_id: int, raw_url: str | None) -> Dict[str, Any] | None:
    url = validate_url(raw_url)
    link_set = await link_repo.update_registration_url(session, set_id, url)
    if link_set is None:
        return None
    return {
        "id": link_set.id,
        "registration_url": link_set.registration_url,
    }


async def save_product_link(
    session: AsyncSession, set_id: int, product_id: str, raw_url: str | None
) -> Dict[str, Any]:
    if product_id not in allowed_product_ids():
        raise LinkValidationError("Неизвестный продукт")

    url = validate_url(raw_url)
    entry = await link_repo.upsert_product_link(session, set_id, product_id, url)
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "url": entry.url,
    }


async def prepare_link_preview(
    session: AsyncSession, set_id: int, product_id: str
) -> Dict[str, Any] | None:
    descriptors = _product_descriptor_map()
    descriptor = descriptors.get(product_id)
    if descriptor is None:
        raise LinkValidationError("Неизвестный продукт")

    link_set = await link_repo.get_set(session, set_id)
    if link_set is None:
        return None

    entries = await link_repo.load_entries_map(session, link_set.id)
    url = entries.get(product_id)
    if not url:
        raise LinkValidationError("Ссылка не заполнена")

    return {
        "set": {"id": link_set.id, "title": link_set.title},
        "product": {"id": descriptor.product_id, "title": descriptor.title},
        "url": url,
    }
