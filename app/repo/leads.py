from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead


async def add(
    session: AsyncSession,
    user_id: int | None,
    username: str | None,
    name: str,
    phone: str,
    comment: str | None,
) -> Lead:
    lead = Lead(
        user_id=user_id,
        username=username,
        name=name,
        phone=phone,
        comment=comment,
        ts=datetime.now(timezone.utc),
    )
    session.add(lead)
    await session.flush()
    return lead


async def list_last(session: AsyncSession, limit: int = 10) -> Sequence[Lead]:
    stmt = select(Lead).order_by(Lead.ts.desc(), Lead.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def count(session: AsyncSession) -> int:
    stmt = select(func.count(Lead.id))
    result = await session.execute(stmt)
    return result.scalar_one()
