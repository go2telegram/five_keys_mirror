"""Repository helpers for habit tracking and reminders."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrackEvent, User

DEFAULT_REMINDER_TIMES: list[str] = ["09:00", "13:00", "19:00"]


@dataclass(slots=True)
class ReminderProfile:
    """Reminder settings snapshot used by the scheduler."""

    user_id: int
    timezone: str | None
    times: list[str]
    last_sent: dict[str, str]


def ensure_profile_defaults(user: User) -> None:
    """Fill nullable reminder fields with safe defaults."""

    if getattr(user, "habit_reminders_enabled", None) is None:
        user.habit_reminders_enabled = False  # type: ignore[assignment]
    if not getattr(user, "habit_reminders_times", None):
        user.habit_reminders_times = []  # type: ignore[assignment]
    if not getattr(user, "habit_reminders_last_sent", None):
        user.habit_reminders_last_sent = {}  # type: ignore[assignment]


async def add_event(
    session: AsyncSession,
    user_id: int,
    kind: str,
    value: int,
    *,
    occurred_at: dt.datetime | None = None,
) -> TrackEvent:
    """Persist a new tracking event for the user."""

    if occurred_at is None:
        occurred_at = dt.datetime.now(dt.timezone.utc)
    event = TrackEvent(user_id=user_id, kind=kind, value=value, ts=occurred_at)
    session.add(event)
    await session.flush()
    return event


async def fetch_events(
    session: AsyncSession,
    user_id: int,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    kinds: Iterable[str] | None = None,
) -> Sequence[TrackEvent]:
    """Return user events ordered from oldest to newest."""

    stmt: Select[tuple[TrackEvent]] = select(TrackEvent).where(TrackEvent.user_id == user_id)
    if since is not None:
        stmt = stmt.where(TrackEvent.ts >= since)
    if until is not None:
        stmt = stmt.where(TrackEvent.ts < until)
    if kinds is not None:
        stmt = stmt.where(TrackEvent.kind.in_(list(kinds)))
    stmt = stmt.order_by(TrackEvent.ts.asc())
    result = await session.execute(stmt)
    return list(result.scalars())


async def list_reminder_profiles(session: AsyncSession) -> list[ReminderProfile]:
    """Fetch reminder configuration for all enabled users."""

    stmt: Select[tuple[User]] = select(User).where(User.habit_reminders_enabled.is_(True))
    result = await session.execute(stmt)
    profiles: list[ReminderProfile] = []
    for user in result.scalars():
        ensure_profile_defaults(user)
        times = [str(item) for item in (user.habit_reminders_times or [])]
        profiles.append(
            ReminderProfile(
                user_id=int(user.id),
                timezone=user.timezone,
                times=times,
                last_sent=dict(user.habit_reminders_last_sent or {}),
            )
        )
    return profiles


async def mark_reminders_sent(
    session: AsyncSession,
    updates: Sequence[tuple[int, str, str]],
) -> None:
    """Persist reminder delivery timestamps."""

    if not updates:
        return
    user_ids = sorted({user_id for user_id, _, _ in updates})
    if not user_ids:
        return
    stmt = select(User).where(User.id.in_(user_ids))
    result = await session.execute(stmt)
    users_by_id = {int(user.id): user for user in result.scalars()}
    for user_id, slot, date_iso in updates:
        user = users_by_id.get(int(user_id))
        if user is None:
            continue
        ensure_profile_defaults(user)
        history = dict(user.habit_reminders_last_sent or {})
        history[slot] = date_iso
        user.habit_reminders_last_sent = history  # type: ignore[assignment]
    await session.flush()


async def set_timezone(session: AsyncSession, user: User, tz_value: str | None) -> None:
    """Update user timezone."""

    user.timezone = tz_value
    await session.flush()


async def set_reminders_enabled(
    session: AsyncSession,
    user: User,
    enabled: bool,
    *,
    ensure_defaults: bool = True,
) -> None:
    """Toggle reminder status and initialise defaults when needed."""

    if ensure_defaults:
        ensure_profile_defaults(user)
    user.habit_reminders_enabled = enabled  # type: ignore[assignment]
    if enabled and not user.habit_reminders_times:
        user.habit_reminders_times = list(DEFAULT_REMINDER_TIMES)  # type: ignore[assignment]
    if not enabled:
        user.habit_reminders_last_sent = {}  # type: ignore[assignment]
    await session.flush()


async def update_reminder_times(session: AsyncSession, user: User, times: Iterable[str]) -> None:
    """Replace reminder schedule and reset delivery history."""

    ensure_profile_defaults(user)
    user.habit_reminders_times = list(times)  # type: ignore[assignment]
    user.habit_reminders_last_sent = {}  # type: ignore[assignment]
    await session.flush()


async def reset_reminder_history(session: AsyncSession, user: User) -> None:
    """Clear stored reminder delivery markers."""

    ensure_profile_defaults(user)
    user.habit_reminders_last_sent = {}  # type: ignore[assignment]
    await session.flush()
