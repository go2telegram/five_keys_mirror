from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromoUsage


async def was_used(session: AsyncSession, user_id: int, code: str) -> bool:
    stmt = select(PromoUsage.id).where(PromoUsage.user_id == user_id, PromoUsage.code == code)
    result = await session.execute(stmt)
    return result.first() is not None


async def mark_used(session: AsyncSession, user_id: int, code: str) -> PromoUsage:
    usage = PromoUsage(
        user_id=user_id,
        code=code,
        used_at=datetime.now(timezone.utc),
    )
    session.add(usage)
    await session.flush()
    return usage
