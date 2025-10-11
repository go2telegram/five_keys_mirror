"""File-based counters for Premium analytics."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

METRICS_PATH = Path("var/metrics.json")

DEFAULT_METRICS: dict[str, Any] = {
    "active_subs": 0,
    "new_subs": 0,
    "ai_plans_sent": 0,
    "plan_chars_total": 0,
    "tracker_events_week": 0,
    "tracker_reset_ts": 0.0,
    "updated_at": 0.0,
}


def _load() -> dict[str, Any]:
    if METRICS_PATH.exists():
        try:
            with METRICS_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
    else:
        data = {}
    merged = DEFAULT_METRICS | data
    return merged


def _save(data: dict[str, Any]) -> None:
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = time.time()
    with METRICS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _update(mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    data = _load()
    mutator(data)
    _save(data)
    return data


def load_metrics() -> dict[str, Any]:
    """Return the latest metrics snapshot."""

    return _load()


def set_active_subs(count: int) -> dict[str, Any]:
    """Persist the number of active subscriptions."""

    count = max(int(count), 0)

    def mutate(data: dict[str, Any]) -> None:
        data["active_subs"] = count

    return _update(mutate)


def record_new_subscription() -> dict[str, Any]:
    """Increment new subscription counter."""

    def mutate(data: dict[str, Any]) -> None:
        data["new_subs"] = int(data.get("new_subs", 0)) + 1

    return _update(mutate)


def record_ai_plan(chars: int) -> dict[str, Any]:
    """Increment counters for generated or sent AI plans."""

    chars = max(int(chars), 0)

    def mutate(data: dict[str, Any]) -> None:
        data["ai_plans_sent"] = int(data.get("ai_plans_sent", 0)) + 1
        data["plan_chars_total"] = int(data.get("plan_chars_total", 0)) + chars

    return _update(mutate)


def record_tracker_event() -> dict[str, Any]:
    """Increment weekly tracker usage counter, resetting every 7 days."""

    reset_after = 7 * 24 * 3600
    now = time.time()

    def mutate(data: dict[str, Any]) -> None:
        last_reset = float(data.get("tracker_reset_ts", 0.0))
        if now - last_reset >= reset_after:
            data["tracker_events_week"] = 0
            data["tracker_reset_ts"] = now
        data["tracker_events_week"] = int(data.get("tracker_events_week", 0)) + 1

    return _update(mutate)
