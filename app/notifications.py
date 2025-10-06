"""Admin notifications and reporting helpers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot

from app.config import settings
from app.storage import (
    AdminEventRecord,
    count_admin_events,
    count_leads,
    count_notify_enabled,
    count_users,
    fetch_admin_events,
    log_admin_event,
)

logger = logging.getLogger(__name__)


class AdminNotifier:
    """Thin wrapper around aiogram Bot for admin broadcasts."""

    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._lock = asyncio.Lock()

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    async def notify(
        self,
        text: str,
        *,
        bot: Bot | None = None,
        silent: bool = False,
    ) -> None:
        target_bot = bot or self._bot
        if target_bot is None:
            logger.debug("Admin notification skipped — bot is not bound yet: %s", text)
            return
        async with self._lock:
            try:
                await target_bot.send_message(
                    settings.ADMIN_ID,
                    text,
                    disable_notification=silent,
                )
            except Exception as exc:  # noqa: BLE001 - admin ping must not crash bot
                logger.warning("Failed to send admin notification: %s", exc)


admin_notifier = AdminNotifier()


async def notify_admins(
    text: str,
    *,
    bot: Bot | None = None,
    silent: bool = False,
    event_kind: str | None = None,
    event_payload: dict | None = None,
) -> None:
    """Send a notification and optionally persist it as an admin event."""
    if event_kind:
        try:
            await log_admin_event(event_kind, event_payload)
        except Exception as exc:  # noqa: BLE001 - logging errors shouldn't block alerts
            logger.warning("Failed to persist admin event %s: %s", event_kind, exc)
    await admin_notifier.notify(text, bot=bot, silent=silent)


@dataclass(slots=True)
class DailyStats:
    total_users: int
    notify_enabled: int
    leads_total: int
    new_users: int
    new_leads: int
    broadcasts: int
    errors: int
    window_hours: int
    generated_at: datetime


async def collect_daily_stats(window_hours: int = 24) -> DailyStats:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    total_users, notify_enabled, leads_total = await asyncio.gather(
        count_users(),
        count_notify_enabled(),
        count_leads(),
    )
    new_users, new_leads, broadcasts, errors = await asyncio.gather(
        count_admin_events("user_registered", since=since),
        count_admin_events("lead_created", since=since),
        count_admin_events("broadcast", since=since),
        count_admin_events("error", since=since),
    )
    return DailyStats(
        total_users=total_users,
        notify_enabled=notify_enabled,
        leads_total=leads_total,
        new_users=new_users,
        new_leads=new_leads,
        broadcasts=broadcasts,
        errors=errors,
        window_hours=window_hours,
        generated_at=now,
    )


def render_stats_report(stats: DailyStats) -> str:
    window = f"за последние {stats.window_hours} ч"
    generated = stats.generated_at.astimezone().strftime("%d.%m %H:%M")
    return (
        "📊 <b>Статистика</b>\n"
        f"Всего пользователей: {stats.total_users}\n"
        f"Напоминания включены: {stats.notify_enabled}\n"
        f"Всего лидов: {stats.leads_total}\n\n"
        f"🕒 {window}:\n"
        f"• Новых пользователей: {stats.new_users}\n"
        f"• Новых лидов: {stats.new_leads}\n"
        f"• Рассылок: {stats.broadcasts}\n"
        f"• Ошибок: {stats.errors}\n\n"
        f"Отчёт сгенерирован {generated}"
    )


def _format_error_payload(event: AdminEventRecord) -> tuple[str, str]:
    payload = event.payload or {}
    fingerprint_raw = payload.get("fingerprint") or payload.get("message") or "unknown"
    last_ts = event.created_at.astimezone().strftime("%d.%m %H:%M")
    sample_raw = payload.get("sample") or payload.get("message") or ""
    fingerprint = escape(fingerprint_raw)
    sample = escape(sample_raw)
    return fingerprint, f"{sample}\nПоследний раз: {last_ts}"


async def render_error_report(
    *,
    window_hours: int = 24,
    limit: int = 10,
) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    events = await fetch_admin_events("error", since=since)
    aggregated: dict[str, dict[str, object]] = {}
    for event in events:
        fingerprint, text = _format_error_payload(event)
        bucket = aggregated.setdefault(
            fingerprint,
            {"count": 0, "sample": text, "latest": event.created_at},
        )
        bucket["count"] = int(bucket["count"]) + 1
        if event.created_at > bucket["latest"]:
            bucket["latest"] = event.created_at
            bucket["sample"] = text
    if not aggregated:
        return "✅ За выбранный период критичных ошибок не найдено."
    items = sorted(
        aggregated.items(),
        key=lambda kv: kv[1]["latest"],
        reverse=True,
    )[:limit]
    lines: list[str] = ["🚨 <b>Ошибки</b>"]
    for idx, (fingerprint, data) in enumerate(items, start=1):
        sample = data["sample"]
        count = data["count"]
        lines.append(f"{idx}) {fingerprint} — {count} раз(а)\n{sample}")
    return "\n\n".join(lines)
