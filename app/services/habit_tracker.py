"""Habit tracking aggregation and helper utilities."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Protocol

from zoneinfo import ZoneInfo

from app.config import settings

_TIME_PATTERN = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")


def is_valid_timezone(name: str) -> bool:
    """Return True if the timezone identifier can be resolved."""

    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


def is_valid_time_slot(value: str) -> bool:
    """Validate HH:MM formatted reminder slots."""

    return bool(_TIME_PATTERN.fullmatch(value.strip()))


class HabitEvent(Protocol):
    """Protocol describing the minimal event interface used by the aggregator."""

    kind: str
    value: int
    ts: dt.datetime


@dataclass(slots=True)
class DailyReport:
    date: dt.date
    totals: Mapping[str, int]


@dataclass(slots=True)
class WeeklyReport:
    start: dt.date
    end: dt.date
    totals: Mapping[str, int]
    averages: Mapping[str, float]


def resolve_timezone(preferred: str | None) -> ZoneInfo:
    """Resolve a zoneinfo object with fallbacks to settings and UTC."""

    candidates = [preferred, getattr(settings, "TIMEZONE", None), "UTC"]
    for candidate in candidates:
        if not candidate:
            continue
        if is_valid_timezone(candidate):
            return ZoneInfo(candidate)
    return ZoneInfo("UTC")


def normalise_times(times: Iterable[str]) -> list[str]:
    """Validate and deduplicate HH:MM timestamps preserving order."""

    seen: set[str] = set()
    normalised: list[str] = []
    for raw in times:
        candidate = raw.strip()
        if not candidate:
            continue
        if not is_valid_time_slot(candidate):
            raise ValueError(f"Invalid time format: {raw!r}")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalised.append(candidate)
    return normalised


def day_bounds(day: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    """Return UTC bounds for the given local day."""

    start_local = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)
    return start_local.astimezone(dt.timezone.utc), end_local.astimezone(dt.timezone.utc)


class HabitAggregator:
    """Aggregate habit tracking events into daily and weekly buckets."""

    def __init__(self, events: Iterable[HabitEvent], tz: ZoneInfo):
        self._tz = tz
        self._daily: MutableMapping[dt.date, dict[str, int]] = {}
        self._kinds: set[str] = set()
        for event in events:
            if not isinstance(event.ts, dt.datetime):
                continue
            ts = event.ts
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            local_ts = ts.astimezone(tz)
            local_day = local_ts.date()
            bucket = self._daily.setdefault(local_day, {})
            bucket[event.kind] = bucket.get(event.kind, 0) + int(event.value)
            self._kinds.add(event.kind)

    @property
    def kinds(self) -> set[str]:
        return set(self._kinds)

    def daily_report(self, day: dt.date) -> DailyReport:
        totals = self._daily.get(day, {})
        return DailyReport(date=day, totals=dict(totals))

    def weekly_report(self, end: dt.date, days: int = 7) -> WeeklyReport:
        if days <= 0:
            raise ValueError("days must be positive")
        start = end - dt.timedelta(days=days - 1)
        totals: dict[str, int] = {}
        for idx in range(days):
            current = start + dt.timedelta(days=idx)
            bucket = self._daily.get(current, {})
            for kind, value in bucket.items():
                totals[kind] = totals.get(kind, 0) + int(value)
        averages = {kind: totals[kind] / days for kind in totals}
        return WeeklyReport(start=start, end=end, totals=totals, averages=averages)

    def streaks(self, end: dt.date, kinds: Iterable[str] | None = None) -> dict[str, int]:
        reference_kinds = list(kinds) if kinds is not None else sorted(self._kinds)
        streaks: dict[str, int] = {kind: 0 for kind in reference_kinds}
        for kind in reference_kinds:
            streak = 0
            current = end
            while True:
                bucket = self._daily.get(current, {})
                value = bucket.get(kind, 0)
                if value > 0:
                    streak += 1
                    current -= dt.timedelta(days=1)
                    continue
                break
            streaks[kind] = streak
        return streaks
