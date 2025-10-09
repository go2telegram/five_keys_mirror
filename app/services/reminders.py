"""Reminder scheduling helpers for water/sleep nudges."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class ReminderConfig:
    """User-level reminder preferences."""

    tz: str = "UTC"
    water_goal_ml: int = 2000
    water_reminders: int = 4
    water_window_start: dt.time = dt.time(9, 0)
    water_window_end: dt.time = dt.time(21, 0)
    bedtime: dt.time | None = dt.time(23, 0)
    enabled: bool = True

    def with_updates(self, **changes: object) -> "ReminderConfig":
        return replace(self, **changes)


class ReminderPlanner:
    """Utility that knows how to plan concrete reminder timestamps."""

    def __init__(self, config: ReminderConfig):
        self._config = config

    @property
    def config(self) -> ReminderConfig:
        return self._config

    def update(self, **changes: object) -> ReminderConfig:
        self._config = self._config.with_updates(**changes)
        return self._config

    # ---- Water -----------------------------------------------------------------

    def water_schedule(self, reference: dt.datetime | None = None) -> list[dt.datetime]:
        """Return reminder instants for the active day."""

        if not self._config.enabled or self._config.water_reminders <= 0:
            return []

        tz = ZoneInfo(self._config.tz)
        reference = reference or dt.datetime.now(tz)
        day = reference.date()
        start = dt.datetime.combine(day, self._config.water_window_start, tz)
        end = dt.datetime.combine(day, self._config.water_window_end, tz)
        if end <= start:
            raise ValueError("water reminder window must be at least 1 minute")

        count = self._config.water_reminders
        if count == 1:
            return [start + (end - start) / 2]

        total_seconds = (end - start).total_seconds()
        step = total_seconds / (count - 1)
        schedule = [start + dt.timedelta(seconds=round(step * idx)) for idx in range(count)]
        return schedule

    def water_message(self, consumed_ml: int, target_ml: int | None = None) -> str:
        target = target_ml or self._config.water_goal_ml
        remaining = max(target - consumed_ml, 0)
        return (
            "💧 Пора пить воду!\n"
            f"Прогресс: {consumed_ml}/{target} мл. Осталось {remaining} мл."
        )

    # ---- Sleep -----------------------------------------------------------------

    def sleep_schedule(self, reference: dt.datetime | None = None) -> list[dt.datetime]:
        if not self._config.enabled or self._config.bedtime is None:
            return []

        tz = ZoneInfo(self._config.tz)
        reference = reference or dt.datetime.now(tz)
        day = reference.date()
        bedtime = dt.datetime.combine(day, self._config.bedtime, tz)
        if bedtime <= reference:
            bedtime += dt.timedelta(days=1)
        reminder_at = bedtime - dt.timedelta(hours=1)
        return [reminder_at]

    def sleep_message(self) -> str:
        if self._config.bedtime is None:
            return "😴 Настройте время отбоя, чтобы получить напоминание."
        bedtime_str = self._config.bedtime.strftime("%H:%M")
        return (
            "😴 Пора готовиться ко сну!\n"
            f"В планах лечь в {bedtime_str}, выключаем экраны и отдыхаем."
        )


def distribute_within(
    start: dt.datetime,
    end: dt.datetime,
    count: int,
) -> list[dt.datetime]:
    """Helper used in tests to validate even distribution."""

    if count <= 0:
        return []
    if end <= start:
        raise ValueError("end must be after start")
    if count == 1:
        return [start + (end - start) / 2]
    step = (end - start) / (count - 1)
    return [start + step * idx for idx in range(count)]
