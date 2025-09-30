from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription


async def get(session: AsyncSession, user_id: int) -> Optional[Subscription]:
    return await session.get(Subscription, user_id)


async def set_plan(
    session: AsyncSession,
    user_id: int,
    plan: str,
    days: int | None = None,
    until: datetime | None = None,
) -> Subscription:
    now = datetime.now(timezone.utc)
    if until is None:
        if days is None:
            raise ValueError("either days or until must be provided")
        until = now + timedelta(days=days)

    subscription = await get(session, user_id)
    if subscription is None:
        subscription = Subscription(
            user_id=user_id, plan=plan, since=now, until=until
        )
        session.add(subscription)
    else:
        subscription.plan = plan
        subscription.since = now
        subscription.until = until

    await session.flush()
    return subscription


async def is_active(
    session: AsyncSession, user_id: int
) -> Tuple[bool, Optional[Subscription]]:
    subscription = await get(session, user_id)
    if subscription is None:
        return False, None

    now = datetime.now(timezone.utc)
    return subscription.until > now, subscription


async def count_active(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    stmt = select(func.count(Subscription.user_id)).where(Subscription.until > now)
    result = await session.execute(stmt)
    return result.scalar_one()
