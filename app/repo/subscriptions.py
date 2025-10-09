from __future__ import annotations

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription


STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_CANCELED = "canceled"


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def get(session: AsyncSession, user_id: int) -> Optional[Subscription]:
    stmt = select(Subscription).where(Subscription.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_plan(
    session: AsyncSession,
    user_id: int,
    plan: str,
    days: int | None = None,
    until: datetime | None = None,
    *,
    status: str = STATUS_ACTIVE,
    provider: str = "manual",
    txn_id: str | None = None,
) -> Subscription:
    now = datetime.now(timezone.utc)
    subscription = await get(session, user_id)
    if until is None:
        if days is None:
            raise ValueError("either days or until must be provided")
        base = now
        if subscription is not None and _ensure_aware(subscription.renewed_at) and _ensure_aware(subscription.renewed_at) > now:
            base = _ensure_aware(subscription.renewed_at) or now
        until = _ensure_aware(base + timedelta(days=days))
    else:
        until = _ensure_aware(until)

    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            plan=plan,
            started_at=now,
            renewed_at=until,
            status=status,
            txn_id=txn_id,
            provider=provider,
        )
        session.add(subscription)
    else:
        subscription.plan = plan
        if subscription.started_at is None:
            subscription.started_at = now
        subscription.renewed_at = until
        subscription.status = status
        subscription.txn_id = txn_id or subscription.txn_id
        subscription.provider = provider

    await session.flush()
    return subscription


async def update_status(
    session: AsyncSession,
    user_id: int,
    status: str,
    *,
    renewed_at: datetime | None = None,
    txn_id: str | None = None,
) -> Optional[Subscription]:
    subscription = await get(session, user_id)
    if subscription is None:
        return None

    subscription.status = status
    subscription.renewed_at = _ensure_aware(renewed_at) if renewed_at is not None else subscription.renewed_at
    if txn_id:
        subscription.txn_id = txn_id
    await session.flush()
    return subscription


async def is_active(session: AsyncSession, user_id: int) -> Tuple[bool, Optional[Subscription]]:
    subscription = await get(session, user_id)
    if subscription is None:
        return False, None

    if subscription.status != STATUS_ACTIVE:
        return False, subscription

    now = datetime.now(timezone.utc)
    renewed_at = _ensure_aware(subscription.renewed_at)
    if renewed_at is not None and renewed_at <= now:
        return False, subscription
    return True, subscription


async def count_active(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    stmt = select(func.count(Subscription.user_id)).where(
        Subscription.status == STATUS_ACTIVE,
        (Subscription.renewed_at.is_(None)) | (Subscription.renewed_at > now),
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def delete(session: AsyncSession, user_id: int) -> None:
    subscription = await get(session, user_id)
    if subscription is None:
        return
    await session.delete(subscription)
    await session.flush()
