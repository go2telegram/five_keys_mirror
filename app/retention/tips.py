"""Daily tips domain logic."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram.utils.keyboard import InlineKeyboardBuilder

DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_SEND_TIME = dt.time(10, 0)

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from aiogram.types import InlineKeyboardMarkup
    from app.db.models import RetentionSetting


def ensure_timezone(tz_name: str | None) -> ZoneInfo:
    """Return a safe zoneinfo object, falling back to Europe/Moscow."""
    try:
        if tz_name:
            return ZoneInfo(tz_name)
    except Exception:
        pass
    return ZoneInfo(DEFAULT_TIMEZONE)


def local_now(now_utc: dt.datetime, tz_name: str | None) -> dt.datetime:
    """Return local datetime in provided timezone, ensuring tz-aware value."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
    tz = ensure_timezone(tz_name)
    return now_utc.astimezone(tz)


def should_send_tip(now_local: dt.datetime, send_time: dt.time | None, last_sent: dt.datetime | None) -> bool:
    """Determine whether a tip should be sent at ``now_local`` moment."""
    target_time = send_time or DEFAULT_SEND_TIME
    if now_local.time() < target_time:
        return False
    if last_sent is None:
        return True
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=dt.timezone.utc)
    last_local = last_sent.astimezone(now_local.tzinfo)
    return last_local.date() < now_local.date()


def clean_tip_text(raw: str) -> str:
    """Collapse whitespace and ensure a leading emoji prefix."""
    cleaned = " ".join(raw.strip().split())
    if not cleaned:
        return "💡 Полезное напоминание дня"
    if cleaned.startswith("💡"):
        return cleaned
    return f"💡 {cleaned}"


def tip_keyboard(tip_id: int | None = None) -> "InlineKeyboardMarkup":
    """Build inline keyboard with disable button and optional reaction."""
    builder = InlineKeyboardBuilder()
    if tip_id is not None:
        builder.button(text="👍 Полезно", callback_data=f"tips:like:{tip_id}")
    builder.button(text="🚫 Отключить напоминания", callback_data="tips:disable")
    return builder.as_markup()


def timezone_label(tz_name: str | None) -> str:
    tz = ensure_timezone(tz_name)
    return getattr(tz, "key", str(tz))


def describe_setting(setting: "RetentionSetting") -> str:
    status = "включены" if setting.tips_enabled else "выключены"
    send_time = (setting.tips_time or DEFAULT_SEND_TIME).strftime("%H:%M")
    tz = timezone_label(setting.timezone)
    return (
        "🔔 Статус ежедневных советов:\n"
        f"• {status}\n"
        f"• время отправки: {send_time}\n"
        f"• часовой пояс: {tz}\n\n"
        "Команды:\n"
        "• /tips on — включить\n"
        "• /tips off — выключить\n"
        "• /tips_time set 09:30 — изменить время\n"
        "• /daily_tip now — получить совет сразу"
    )
