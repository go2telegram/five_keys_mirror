from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order


async def get(session: AsyncSession, order_id: int) -> Optional[Order]:
    return await session.get(Order, order_id)


async def get_by_payload_hash(session: AsyncSession, payload_hash: str) -> Optional[Order]:
    stmt = select(Order).where(Order.payload_hash == payload_hash)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    currency: str,
    product: str,
    provider: str,
    payload_json: dict[str, Any],
    payload_hash: str,
) -> Order:
    existing = await get_by_payload_hash(session, payload_hash)
    if existing:
        return existing

    order = Order(
        user_id=user_id,
        amount=amount,
        currency=currency,
        product=product,
        provider=provider,
        payload_json=payload_json,
        payload_hash=payload_hash,
    )
    session.add(order)
    await session.flush()
    return order


async def update_status(session: AsyncSession, order: Order, status: str) -> Order:
    order.status = status
    await session.flush()
    return order


async def attach_payload(session: AsyncSession, order: Order, payload: dict[str, Any]) -> Order:
    order.payload_json = payload
    await session.flush()
    return order
