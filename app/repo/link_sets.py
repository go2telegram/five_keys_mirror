"""Persistence helpers for managing partner link sets."""

from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LinkEntry, LinkSet


async def list_sets(session: AsyncSession) -> Sequence[LinkSet]:
    stmt = select(LinkSet).order_by(LinkSet.title)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_set(session: AsyncSession, set_id: int) -> LinkSet | None:
    return await session.get(LinkSet, set_id)


async def get_active_set(session: AsyncSession) -> LinkSet | None:
    stmt = select(LinkSet).where(LinkSet.is_active.is_(True)).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first()


async def ensure_entries(session: AsyncSession, link_set: LinkSet, product_ids: Iterable[str]) -> None:
    stmt = select(LinkEntry.product_id).where(LinkEntry.set_id == link_set.id)
    result = await session.execute(stmt)
    existing = {row for row, in result.all()}

    missing = [pid for pid in product_ids if pid not in existing]
    if not missing:
        return

    session.add_all(LinkEntry(set_id=link_set.id, product_id=pid) for pid in missing)
    await session.flush()


async def load_entries_map(session: AsyncSession, set_id: int) -> dict[str, str | None]:
    stmt = select(LinkEntry.product_id, LinkEntry.url).where(LinkEntry.set_id == set_id)
    result = await session.execute(stmt)
    return {product_id: url for product_id, url in result.all()}


async def set_active(session: AsyncSession, set_id: int) -> LinkSet | None:
    target = await session.get(LinkSet, set_id)
    if target is None:
        return None

    await session.execute(update(LinkSet).where(LinkSet.is_active.is_(True)).values(is_active=False))
    target.is_active = True
    await session.flush()
    return target


async def update_registration_url(session: AsyncSession, set_id: int, url: str | None) -> LinkSet | None:
    link_set = await session.get(LinkSet, set_id)
    if link_set is None:
        return None

    link_set.registration_url = url
    await session.flush()
    return link_set


async def upsert_product_link(
    session: AsyncSession, set_id: int, product_id: str, url: str | None
) -> LinkEntry:
    stmt = select(LinkEntry).where(
        LinkEntry.set_id == set_id,
        LinkEntry.product_id == product_id,
    )
    result = await session.execute(stmt)
    entry = result.scalars().first()

    if entry is None:
        entry = LinkEntry(set_id=set_id, product_id=product_id, url=url)
        session.add(entry)
    else:
        entry.url = url

    await session.flush()
    return entry
