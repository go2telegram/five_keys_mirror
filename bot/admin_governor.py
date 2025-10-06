from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable
from zoneinfo import ZoneInfo

from app.config import settings
from app.governor_service import get_engine


def _format_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        value = dt.datetime.fromisoformat(ts)
    except ValueError:
        return ts
    tz = ZoneInfo(settings.TZ)
    value = value.replace(tzinfo=dt.timezone.utc).astimezone(tz)
    return value.strftime("%d.%m %H:%M")


def _format_action(action: Dict[str, object]) -> str:
    if not action:
        return "—"
    key, value = next(iter(action.items()))
    return f"{key}: {value}"


def render_governor_status() -> str:
    engine = get_engine()
    status = engine.get_status()

    lines: list[str] = ["🛡 Governor", ""]
    last_run = _format_ts(status.get("last_run_at"))
    lines.append(f"Последний прогон: {last_run}")

    rules: Iterable[Dict[str, object]] = status.get("rules", [])
    if not rules:
        lines.append("Правил нет (rules.yml пуст).")
    else:
        lines.append("\nПравила:")
        for item in rules:
            action = _format_action(item.get("do", {}))
            state = "ACTIVE" if item.get("active") else "ok"
            lines.append(f"• if {item.get('if')} → {action} — {state}")
            lines.append(
                "  "
                + f"последний триггер: {_format_ts(item.get('last_triggered'))}, восстановление: {_format_ts(item.get('last_cleared'))}"
            )

    history = status.get("history", [])
    if history:
        lines.append("\nПоследние срабатывания:")
        for entry in history[:5]:
            action = _format_action(entry.get("action", {}))
            lines.append(f"• {_format_ts(entry.get('ts'))} — {entry.get('rule')} → {action}")
            if details := entry.get("details"):
                lines.append(f"  {details}")
    return "\n".join(lines)


__all__ = ["render_governor_status"]
