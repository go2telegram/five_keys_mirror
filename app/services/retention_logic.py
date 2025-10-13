from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def ensure_timezone(tz_name: str | None) -> ZoneInfo:
    try:
        if tz_name:
            return ZoneInfo(tz_name)
    except Exception:
        pass
    return ZoneInfo("UTC")


def ensure_aware(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=dt.timezone.utc)
    return moment


def should_send_tip(
    now_local: dt.datetime, send_time: dt.time, last_sent: dt.datetime | None
) -> bool:
    if now_local.time() < send_time:
        return False
    if last_sent is None:
        return True
    last_sent = ensure_aware(last_sent).astimezone(now_local.tzinfo or dt.timezone.utc)
    return last_sent.date() < now_local.date()


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
