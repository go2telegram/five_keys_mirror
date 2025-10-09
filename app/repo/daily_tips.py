from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyTip, DailyTipSubscription


async def random_tip(session: AsyncSession) -> DailyTip | None:
    stmt: Select[DailyTip] = (
        select(DailyTip)
        .where(DailyTip.active == 1)
        .order_by(func.random())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_subscription(
    session: AsyncSession,
    user_id: int,
    *,
    default_timezone: str,
) -> DailyTipSubscription:
    subscription = await session.get(DailyTipSubscription, user_id)
    if subscription:
        if not subscription.timezone:
            subscription.timezone = default_timezone
            await session.flush()
        return subscription

    subscription = DailyTipSubscription(
        user_id=user_id,
        timezone=default_timezone,
        enabled=0,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def update_timezone(
    session: AsyncSession,
    user_id: int,
    timezone: str,
) -> DailyTipSubscription:
    subscription = await get_or_create_subscription(session, user_id, default_timezone=timezone)
    subscription.timezone = timezone
    await session.flush()
    return subscription


async def set_enabled(
    session: AsyncSession,
    user_id: int,
    *,
    enabled: bool,
    next_send_at: dt.datetime | None = None,
) -> DailyTipSubscription:
    subscription = await get_or_create_subscription(
        session,
        user_id,
        default_timezone="UTC",
    )
    subscription.enabled = 1 if enabled else 0
    subscription.next_send_at = next_send_at if enabled else None
    await session.flush()
    return subscription


async def due_subscriptions(
    session: AsyncSession,
    now: dt.datetime,
    *,
    limit: int = 64,
) -> Sequence[DailyTipSubscription]:
    stmt: Select[DailyTipSubscription] = (
        select(DailyTipSubscription)
        .where(
            DailyTipSubscription.enabled == 1,
            DailyTipSubscription.next_send_at.is_not(None),
            DailyTipSubscription.next_send_at <= now,
        )
        .order_by(DailyTipSubscription.next_send_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def mark_sent(
    session: AsyncSession,
    subscription: DailyTipSubscription,
    *,
    next_send_at: dt.datetime,
    tip_id: Optional[int],
) -> DailyTipSubscription:
    subscription.next_send_at = next_send_at
    subscription.last_tip_id = tip_id
    await session.flush()
    return subscription
