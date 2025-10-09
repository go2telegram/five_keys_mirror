import datetime as dt
from dataclasses import dataclass

import pytest
from zoneinfo import ZoneInfo

from app.services.habit_tracker import HabitAggregator


@dataclass
class _Event:
    kind: str
    value: int
    ts: dt.datetime


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)


def test_daily_and_weekly_aggregation():
    tz = ZoneInfo("Europe/Moscow")
    events = [
        _Event("water", 250, _utc(2024, 1, 8, 5)),
        _Event("stress", 3, _utc(2024, 1, 8, 6)),
        _Event("water", 250, _utc(2024, 1, 9, 5)),
        _Event("water", 300, _utc(2024, 1, 10, 6)),
        _Event("water", 200, _utc(2024, 1, 10, 10)),
        _Event("sleep", 7, _utc(2024, 1, 10, 2)),
    ]

    aggregator = HabitAggregator(events, tz)
    today = dt.date(2024, 1, 10)

    daily = aggregator.daily_report(today)
    assert daily.totals["water"] == 500
    assert daily.totals["sleep"] == 7
    assert "stress" not in daily.totals

    weekly = aggregator.weekly_report(today)
    assert weekly.totals["water"] == 1000
    assert weekly.totals["sleep"] == 7
    assert pytest.approx(weekly.averages["water"], rel=1e-6) == 1000 / 7

    streaks = aggregator.streaks(today, kinds=["water", "sleep", "stress"])
    assert streaks["water"] == 3
    assert streaks["sleep"] == 1
    assert streaks["stress"] == 0


def test_weekly_requires_positive_days():
    tz = ZoneInfo("UTC")
    aggregator = HabitAggregator([], tz)
    with pytest.raises(ValueError):
        aggregator.weekly_report(dt.date(2024, 1, 1), days=0)
