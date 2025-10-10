"""Administrative helpers for monitoring security status via bot commands."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from security.monitor import security_monitor

router = Router(name="security_admin")


def _escape(value: Any) -> str:
    """Return a safe HTML representation of arbitrary metadata."""

    return escape(str(value), quote=False)


def _format_event(event: dict[str, Any]) -> str:
    ts = datetime.fromtimestamp(event["timestamp"]).strftime("%H:%M:%S")
    meta = event.get("metadata") or {}
    details = []
    if "ip" in meta:
        details.append(f"IP: {_escape(meta['ip'])}")
    if "path" in meta:
        details.append(f"path={_escape(meta['path'])}")
    if "status" in meta:
        details.append(f"status={_escape(meta['status'])}")
    if "pattern" in meta:
        details.append(f"pattern={_escape(meta['pattern'])}")
    if "count" in meta:
        details.append(f"count={_escape(meta['count'])}")
    meta_str = (" | ".join(details)) if details else ""
    suffix = f" — {meta_str}" if meta_str else ""
    event_type = _escape(event.get("event_type", ""))
    severity = _escape(event.get("severity", ""))
    description = _escape(event.get("description", ""))
    return f"[{ts}] {event_type} ({severity}) — {description}{suffix}"


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.ADMIN_ID)


@router.message(Command("security_status"))
async def handle_security_status(message: Message) -> None:
    if not _is_admin(message):
        return

    snapshot = security_monitor.get_status()
    counters = snapshot.get("event_counters", {})
    recent = snapshot.get("recent_events", [])
    lines = ["🛡 <b>Security status</b>"]
    lines.append(f"Включено: {'да' if snapshot.get('enabled') else 'нет'}")
    lines.append(f"Всего запросов: {snapshot.get('total_requests', 0)}")
    lines.append(f"Уникальных источников: {snapshot.get('unique_sources', 0)}")
    if counters:
        counters_str = ", ".join(f"{k}: {v}" for k, v in counters.items())
        lines.append(f"Счётчики событий — {counters_str}")
    else:
        lines.append("Событий ещё нет.")

    if recent:
        lines.append("\nПоследние события:")
        for event in recent[:5]:
            lines.append(_format_event(event))
    await message.answer("\n".join(lines))


@router.message(Command("security_recent"))
async def handle_security_recent(message: Message) -> None:
    if not _is_admin(message):
        return

    recent = security_monitor.get_status().get("recent_events", [])[:10]
    if not recent:
        await message.answer("Пока всё чисто.")
        return

    lines = ["🗒 Последние события:"]
    lines.extend(_format_event(event) for event in recent)
    await message.answer("\n".join(lines))
