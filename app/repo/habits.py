"""Repository helpers for the habit tracker subsystem."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrackEvent


class HabitKind(str, Enum):
    """Kinds of tracked events supported by the habit tracker."""

    WATER = "water"
    SLEEP = "sleep"
    STRESS = "stress"
    STEPS = "steps"

    @classmethod
    def parse(cls, value: str | "HabitKind") -> "HabitKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"Unsupported habit kind: {value!r}") from exc


@dataclass(slots=True)
class HabitEvent:
    """A lightweight projection of :class:`~app.db.models.TrackEvent`."""

    id: int
    user_id: int
    kind: HabitKind
    value: float
    ts: dt.datetime

    @classmethod
    def from_model(cls, model: TrackEvent) -> "HabitEvent":
        return cls(id=model.id, user_id=model.user_id, kind=HabitKind.parse(model.kind), value=model.value, ts=model.ts)


async def add_event(
    session: AsyncSession,
    user_id: int,
    kind: str | HabitKind,
    value: float,
    ts: dt.datetime | None = None,
) -> TrackEvent:
    """Persist a new tracking event."""

    habit = HabitKind.parse(kind)
    timestamp = ts or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)

    if habit is HabitKind.STRESS and not 0 <= value <= 10:
        raise ValueError("stress value must be in range 0..10")
    if habit in (HabitKind.WATER, HabitKind.STEPS) and value <= 0:
        raise ValueError("water and steps must be positive")
    if habit is HabitKind.SLEEP and value <= 0:
        raise ValueError("sleep duration must be positive")

    event = TrackEvent(user_id=user_id, kind=habit.value, value=float(value), ts=timestamp)
    session.add(event)
    await session.flush()
    return event


async def events_between(
    session: AsyncSession,
    user_id: int,
    start: dt.datetime,
    end: dt.datetime,
    kinds: Iterable[str | HabitKind] | None = None,
) -> list[HabitEvent]:
    """Return events for a user between two instants (UTC-aware)."""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError("start must be earlier than end")

    conditions = [TrackEvent.user_id == user_id, TrackEvent.ts >= start, TrackEvent.ts < end]
    if kinds:
        kind_values = [HabitKind.parse(kind).value for kind in kinds]
        conditions.append(TrackEvent.kind.in_(kind_values))

    stmt = select(TrackEvent).where(and_(*conditions)).order_by(TrackEvent.ts.asc())
    result = await session.execute(stmt)
    return [HabitEvent.from_model(model) for model in result.scalars()]


async def last_event(session: AsyncSession, user_id: int, kind: str | HabitKind) -> HabitEvent | None:
    """Fetch the latest event of the given kind for a user."""

    habit = HabitKind.parse(kind)
    stmt = (
        select(TrackEvent)
        .where(TrackEvent.user_id == user_id, TrackEvent.kind == habit.value)
        .order_by(TrackEvent.ts.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    model = result.scalar_one_or_none()
    if model is None:
        return None
    return HabitEvent.from_model(model)


async def unique_event_dates(
    session: AsyncSession,
    user_id: int,
    kind: str | HabitKind,
    tz: dt.tzinfo,
) -> Sequence[dt.date]:
    """Return sorted unique local dates with events for the user/kind."""

    habit = HabitKind.parse(kind)
    stmt = select(TrackEvent.ts).where(TrackEvent.user_id == user_id, TrackEvent.kind == habit.value).order_by(TrackEvent.ts.asc())
    result = await session.execute(stmt)
    dates: list[dt.date] = []
    seen: set[dt.date] = set()
    for (timestamp,) in result:
        local_date = timestamp.astimezone(tz).date()
        if local_date not in seen:
            seen.add(local_date)
            dates.append(local_date)
    return dates
*** End File
