from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.retention import tips as tips_logic


def ensure_timezone(tz_name: str | None) -> ZoneInfo:
    """Backward-compatible proxy to :func:`app.retention.tips.ensure_timezone`."""
    return tips_logic.ensure_timezone(tz_name)


def ensure_aware(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=dt.timezone.utc)
    return moment


def should_send_tip(now_local: dt.datetime, send_time: dt.time, last_sent: dt.datetime | None) -> bool:
    return tips_logic.should_send_tip(now_local, send_time, last_sent)


def water_goal_from_weight(weight: float | None) -> int:
    if weight is None or weight <= 0:
        return 2000
    goal = int(round(weight * 30))
    return max(goal, 1500)


def water_reminders_from_weight(weight: float | None) -> int:
    if weight is None:
        return 3
    return 4 if weight >= 75 else 3


def water_consumed(goal_ml: int, reminders: int, sent_count: int) -> int:
    if reminders <= 0:
        return 0
    progress = goal_ml * sent_count / reminders
    return int(round(progress))
