"""High level helpers for the habit tracking flows."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from statistics import mean
from typing import Dict, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.repo import habits as habits_repo


@dataclass(slots=True)
class HabitSummary:
    """Aggregated statistics for a single day."""

    date: dt.date
    timezone: str
    water_ml: int
    sleep_hours: float
    stress_avg: float | None
    stress_samples: int
    steps: int
    events: int

    def as_text(self) -> str:
        parts = [f"📅 {self.date.strftime('%d %b %Y')} ({self.timezone})"]
        parts.append(f"💧 Вода: {self.water_ml} мл")
        parts.append(f"😴 Сон: {self.sleep_hours:.1f} ч")
        if self.stress_avg is not None:
            parts.append(f"🧘 Стресс: {self.stress_avg:.1f}/10 ({self.stress_samples})")
        else:
            parts.append("🧘 Стресс: нет замеров")
        parts.append(f"👣 Шаги: {self.steps}")
        parts.append(f"🗒️ Событий: {self.events}")
        return "\n".join(parts)


@dataclass(slots=True)
class HabitStreak:
    """Information about consecutive-day streaks."""

    kind: habits_repo.HabitKind
    current: int
    longest: int
    last_event: dt.datetime | None

    def as_text(self) -> str:
        emoji = {
            habits_repo.HabitKind.WATER: "💧",
            habits_repo.HabitKind.SLEEP: "😴",
            habits_repo.HabitKind.STRESS: "🧘",
            habits_repo.HabitKind.STEPS: "👣",
        }[self.kind]
        last_part = "—" if self.last_event is None else self.last_event.strftime("%d %b")
        return f"{emoji} {self.kind.value}: серия {self.current}, рекорд {self.longest}, последнее: {last_part}"


def _ensure_tz(tz_name: str | dt.tzinfo) -> ZoneInfo:
    if isinstance(tz_name, dt.tzinfo):
        if isinstance(tz_name, ZoneInfo):
            return tz_name
        return ZoneInfo(str(tz_name))
    return ZoneInfo(tz_name)


async def track(
    session: AsyncSession,
    user_id: int,
    kind: str | habits_repo.HabitKind,
    value: float,
    ts: dt.datetime | None = None,
) -> habits_repo.HabitEvent:
    """Persist a new event and return a lightweight projection."""

    event = await habits_repo.add_event(session, user_id, kind, value, ts=ts)
    return habits_repo.HabitEvent.from_model(event)


async def day_summary(
    session: AsyncSession,
    user_id: int,
    day: dt.date,
    tz: str | dt.tzinfo,
) -> HabitSummary:
    """Aggregate stats for the requested calendar day."""

    tzinfo = _ensure_tz(tz)
    start = dt.datetime.combine(day, dt.time.min, tzinfo)
    end = start + dt.timedelta(days=1)
    start_utc = start.astimezone(dt.timezone.utc)
    end_utc = end.astimezone(dt.timezone.utc)

    events = await habits_repo.events_between(session, user_id, start_utc, end_utc)
    water = sum(event.value for event in events if event.kind is habits_repo.HabitKind.WATER)
    sleep = sum(event.value for event in events if event.kind is habits_repo.HabitKind.SLEEP)
    stress_values = [event.value for event in events if event.kind is habits_repo.HabitKind.STRESS]
    steps = sum(event.value for event in events if event.kind is habits_repo.HabitKind.STEPS)

    stress_avg = mean(stress_values) if stress_values else None

    tz_label = getattr(tzinfo, "key", str(tzinfo))

    return HabitSummary(
        date=day,
        timezone=str(tz_label),
        water_ml=int(round(water)),
        sleep_hours=round(sleep, 1),
        stress_avg=round(stress_avg, 1) if stress_avg is not None else None,
        stress_samples=len(stress_values),
        steps=int(round(steps)),
        events=len(events),
    )


async def today_summary(session: AsyncSession, user_id: int, tz: str | dt.tzinfo) -> HabitSummary:
    tzinfo = _ensure_tz(tz)
    now = dt.datetime.now(tzinfo)
    return await day_summary(session, user_id, now.date(), tzinfo)


async def streak_for_kind(
    session: AsyncSession,
    user_id: int,
    kind: str | habits_repo.HabitKind,
    tz: str | dt.tzinfo,
) -> HabitStreak:
    tzinfo = _ensure_tz(tz)
    habit = habits_repo.HabitKind.parse(kind)
    dates = await habits_repo.unique_event_dates(session, user_id, habit, tzinfo)
    last_event = await habits_repo.last_event(session, user_id, habit)

    today = dt.datetime.now(tzinfo).date()
    dates_set = set(dates)

    current = 0
    cursor = today
    while cursor in dates_set:
        current += 1
        cursor -= dt.timedelta(days=1)

    longest = 0
    run = 0
    previous: dt.date | None = None
    for date in dates:
        if previous is not None and (date - previous).days == 1:
            run += 1
        else:
            run = 1
        previous = date
        longest = max(longest, run)

    return HabitStreak(
        kind=habit,
        current=current,
        longest=longest,
        last_event=None if last_event is None else last_event.ts.astimezone(tzinfo),
    )


async def all_streaks(session: AsyncSession, user_id: int, tz: str | dt.tzinfo) -> Dict[str, HabitStreak]:
    tzinfo = _ensure_tz(tz)
    result: Dict[str, HabitStreak] = {}
    for kind in habits_repo.HabitKind:
        result[kind.value] = await streak_for_kind(session, user_id, kind, tzinfo)
    return result


def streaks_text(streaks: Mapping[str, HabitStreak]) -> str:
    lines = ["🔥 Серии привычек"]
    for kind in habits_repo.HabitKind:
        streak = streaks.get(kind.value)
        if streak is None:
            continue
        lines.append(streak.as_text())
    return "\n".join(lines)
