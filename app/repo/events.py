from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event


async def log(session: AsyncSession, user_id: Optional[int], name: str, meta: Optional[Dict[str, Any]] = None) -> Event:
    event = Event(
        user_id=user_id,
        name=name,
        meta=meta or {},
        ts=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


async def last_by(session: AsyncSession, user_id: int, name: str) -> Optional[Event]:
    stmt = select(Event).where(Event.user_id == user_id, Event.name == name).order_by(Event.ts.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def recent_plans(session: AsyncSession, user_id: int, limit: int = 3) -> Sequence[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.name == "plan_generated")
        .order_by(Event.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def stats(
    session: AsyncSession,
    name: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> int:
    stmt = select(func.count(Event.id))
    if name is not None:
        stmt = stmt.where(Event.name == name)
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    if until is not None:
        stmt = stmt.where(Event.ts < until)

    result = await session.execute(stmt)
    return result.scalar_one()


async def notify_recipients(session: AsyncSession) -> Sequence[int]:
    status_events = ("notify_on", "notify_off")
    subq = (
        select(Event.user_id, func.max(Event.ts).label("last_ts"))
        .where(Event.name.in_(status_events), Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )

    stmt = (
        select(Event.user_id)
        .join(
            subq,
            (Event.user_id == subq.c.user_id) & (Event.ts == subq.c.last_ts),
        )
        .where(Event.name == "notify_on")
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0] is not None]
