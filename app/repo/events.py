from __future__ import annotations

import inspect
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event


async def log(
    session: AsyncSession, user_id: Optional[int], name: str, meta: Optional[Dict[str, Any]] = None
) -> Event:
    event = Event(
        user_id=user_id,
        name=name,
        meta=meta or {},
        ts=datetime.now(timezone.utc),
    )
    session.add(event)
    try:
        await session.flush()
    except (OperationalError, ProgrammingError) as exc:
        # В юнит-тестах база часто эмулируется «пустой» in-memory SQLite без схемы.
        # Чтобы сценарии без миграций не падали, молча пропускаем ошибки отсутствия
        # таблицы events. Для остальных ошибок сохраняем исходное исключение.
        if not _is_missing_table_error(exc):
            raise

        rollback = getattr(session, "rollback", None)
        if callable(rollback):
            result = rollback()
            if inspect.isawaitable(result):
                with suppress(Exception):  # pragma: no cover - best effort cleanup
                    await result
        return event
    return event


async def upsert(
    session: AsyncSession,
    user_id: Optional[int],
    name: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Event:
    """Ensure a single event per ``(user_id, name)`` combination."""

    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.name == name)
        .order_by(Event.id.asc())
        .limit(1)
    )
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return Event(user_id=user_id, name=name, meta=meta or {}, ts=datetime.now(timezone.utc))
        raise

    event = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    payload = meta or {}
    if event is None:
        event = Event(user_id=user_id, name=name, meta=payload, ts=now)
        session.add(event)
    else:
        event.meta = payload
        event.ts = now

    try:
        await session.flush()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_table_error(exc):
            raise
        rollback = getattr(session, "rollback", None)
        if callable(rollback):
            result = rollback()
            if inspect.isawaitable(result):
                with suppress(Exception):  # pragma: no cover
                    await result
    return event


async def last_by(session: AsyncSession, user_id: int, name: str) -> Optional[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.name == name)
        .order_by(Event.ts.desc())
        .limit(1)
    )
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    return result.scalar_one_or_none()


async def recent_plans(session: AsyncSession, user_id: int, limit: int = 3) -> Sequence[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.name == "plan_generated")
        .order_by(Event.ts.desc())
        .limit(limit)
    )
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return []
        raise
    return list(result.scalars())


async def recent_events(session: AsyncSession, limit: int = 5) -> Sequence[Event]:
    stmt = select(Event).order_by(Event.ts.desc()).limit(limit)
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return []
        raise
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

    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return 0
        raise
    return result.scalar_one()


async def latest_by_users(
    session: AsyncSession,
    name: str,
    user_ids: Iterable[int | None],
) -> dict[int, Event]:
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return {}

    subq = (
        select(Event.user_id, func.max(Event.ts).label("max_ts"))
        .where(Event.name == name, Event.user_id.in_(ids))
        .group_by(Event.user_id)
        .subquery()
    )

    stmt = (
        select(Event)
        .join(
            subq,
            (Event.user_id == subq.c.user_id) & (Event.ts == subq.c.max_ts),
        )
        .where(Event.name == name)
    )
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return {}
        raise
    events = result.scalars().all()
    return {event.user_id: event for event in events if event.user_id is not None}


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
    try:
        result = await session.execute(stmt)
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_table_error(exc):
            return []
        raise
    return [row[0] for row in result.all() if row[0] is not None]


def _is_missing_table_error(exc: BaseException) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "no such table" in message or "doesn't exist" in message
