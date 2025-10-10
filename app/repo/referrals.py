from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Referral


async def upsert_referral(session: AsyncSession, referrer_id: int, invited_id: int) -> Referral:
    """Create a referral record if missing, otherwise return the existing one."""

    stmt = select(Referral).where(Referral.user_id == referrer_id, Referral.invited_id == invited_id)
    result = await session.execute(stmt)
    referral = result.scalar_one_or_none()
    if referral is not None:
        return referral

    referral = Referral(
        user_id=referrer_id,
        invited_id=invited_id,
        joined_at=datetime.now(timezone.utc),
    )
    session.add(referral)
    await session.flush()
    return referral


async def create(session: AsyncSession, referrer_id: int, invited_id: int) -> Referral:
    """Backward-compatible helper delegating to :func:`upsert_referral`."""

    referral = await upsert_referral(session, referrer_id, invited_id)
    return referral


async def convert(session: AsyncSession, invited_id: int, bonus_days: int = 0) -> Optional[Referral]:
    referral = await get_by_invited(session, invited_id)
    if referral is None:
        return None

    referral.converted_at = datetime.now(timezone.utc)
    referral.bonus_days = bonus_days
    await session.flush()
    return referral


async def get_by_invited(session: AsyncSession, invited_id: int) -> Optional[Referral]:
    stmt = select(Referral).where(Referral.invited_id == invited_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def top_referrers(
    session: AsyncSession,
    period: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None,
    limit: int = 10,
) -> Sequence[Tuple[int, int]]:
    stmt = select(Referral.user_id, func.count(Referral.id))
    if period:
        start, end = period
        if start is not None:
            stmt = stmt.where(Referral.joined_at >= start)
        if end is not None:
            stmt = stmt.where(Referral.joined_at < end)
    stmt = stmt.group_by(Referral.user_id).order_by(func.count(Referral.id).desc()).limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def converted_count(session: AsyncSession) -> int:
    stmt = select(func.count(Referral.id)).where(Referral.converted_at.is_not(None))
    result = await session.execute(stmt)
    return result.scalar_one()


async def stats_for_referrer(session: AsyncSession, referrer_id: int) -> tuple[int, int]:
    invited_stmt = select(func.count(Referral.id)).where(Referral.user_id == referrer_id)
    converted_stmt = select(func.count(Referral.id)).where(
        Referral.user_id == referrer_id, Referral.converted_at.is_not(None)
    )

    invited_res = await session.execute(invited_stmt)
    converted_res = await session.execute(converted_stmt)
    invited = invited_res.scalar_one()
    converted = converted_res.scalar_one()
    return invited, converted


async def list_for(
    session: AsyncSession,
    referrer_id: int,
    limit: int,
    offset: int,
    period: Optional[str] = None,
) -> list[Referral]:
    stmt = select(Referral).where(Referral.user_id == referrer_id)
    stmt = _apply_period_filter(stmt, period)
    stmt = stmt.order_by(Referral.joined_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars())


async def count_for(
    session: AsyncSession,
    referrer_id: int,
    period: Optional[str] = None,
) -> int:
    stmt = select(func.count(Referral.id)).where(Referral.user_id == referrer_id)
    stmt = _apply_period_filter(stmt, period)
    result = await session.execute(stmt)
    return result.scalar_one()


def _apply_period_filter(stmt, period: Optional[str]):
    if period in (None, "", "all"):
        return stmt
    now = datetime.now(timezone.utc)
    delta: Optional[timedelta]
    if period == "7d":
        delta = timedelta(days=7)
    elif period == "30d":
        delta = timedelta(days=30)
    else:
        delta = None
    if delta is None:
        return stmt
    threshold = now - delta
    return stmt.where(Referral.joined_at >= threshold)
