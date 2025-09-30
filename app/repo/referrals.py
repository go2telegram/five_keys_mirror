from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Referral


async def create(
    session: AsyncSession, referrer_id: int, invited_id: int
) -> Referral:
    referral = Referral(
        referrer_id=referrer_id,
        invited_id=invited_id,
        joined_at=datetime.now(timezone.utc),
    )
    session.add(referral)
    await session.flush()
    return referral


async def convert(
    session: AsyncSession, invited_id: int, bonus_days: int
) -> Optional[Referral]:
    referral = await get_by_invited(session, invited_id)
    if referral is None:
        return None

    referral.converted_at = datetime.now(timezone.utc)
    referral.bonus_days = bonus_days
    await session.flush()
    return referral


async def get_by_invited(
    session: AsyncSession, invited_id: int
) -> Optional[Referral]:
    stmt = select(Referral).where(Referral.invited_id == invited_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def top_referrers(
    session: AsyncSession,
    period: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None,
    limit: int = 10,
) -> Sequence[Tuple[int, int]]:
    stmt = select(Referral.referrer_id, func.count(Referral.id))
    if period:
        start, end = period
        if start is not None:
            stmt = stmt.where(Referral.joined_at >= start)
        if end is not None:
            stmt = stmt.where(Referral.joined_at < end)
    stmt = (
        stmt.group_by(Referral.referrer_id)
        .order_by(func.count(Referral.id).desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def converted_count(session: AsyncSession) -> int:
    stmt = select(func.count(Referral.id)).where(Referral.converted_at.is_not(None))
    result = await session.execute(stmt)
    return result.scalar_one()


async def stats_for_referrer(
    session: AsyncSession, referrer_id: int
) -> tuple[int, int]:
    invited_stmt = select(func.count(Referral.id)).where(
        Referral.referrer_id == referrer_id
    )
    converted_stmt = select(func.count(Referral.id)).where(
        Referral.referrer_id == referrer_id, Referral.converted_at.is_not(None)
    )

    invited_res = await session.execute(invited_stmt)
    converted_res = await session.execute(converted_stmt)
    invited = invited_res.scalar_one()
    converted = converted_res.scalar_one()
    return invited, converted
