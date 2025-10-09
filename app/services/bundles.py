"""Bundle helpers for commerce upsell flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bundle


@dataclass(slots=True)
class BundleSuggestion:
    bundle: Bundle
    overlap: int


async def load_active_bundles(session: AsyncSession) -> list[Bundle]:
    stmt = select(Bundle).where(Bundle.active == 1).order_by(Bundle.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars())


def _normalize_items(bundle: Bundle) -> set[str]:
    raw = bundle.items_json or {}
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("products") or raw
        if isinstance(items, dict):
            return {str(key) for key, value in items.items() if value}
        if isinstance(items, (list, tuple, set)):
            return {str(item) for item in items}
    if isinstance(raw, (list, tuple, set)):
        return {str(item) for item in raw}
    return set()


def score_bundle(bundle: Bundle, products: Sequence[str]) -> BundleSuggestion | None:
    items = _normalize_items(bundle)
    if not items:
        return None
    overlap = len(items.intersection({str(p) for p in products}))
    if overlap == 0:
        return None
    return BundleSuggestion(bundle=bundle, overlap=overlap)


async def suggest_bundle(session: AsyncSession, products: Iterable[str]) -> Bundle | None:
    product_list = [str(p) for p in products if p]
    if not product_list:
        return None
    bundles = await load_active_bundles(session)
    suggestions = [score_bundle(bundle, product_list) for bundle in bundles]
    ranked = sorted(
        (s for s in suggestions if s is not None),
        key=lambda s: (s.overlap, float(getattr(s.bundle, "price", 0.0))),
        reverse=True,
    )
    if not ranked:
        return None
    return ranked[0].bundle


__all__ = ["BundleSuggestion", "load_active_bundles", "score_bundle", "suggest_bundle"]
