# app/scheduler/jobs.py
import asyncio
import datetime as dt
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.notifications import (
    collect_daily_stats,
    notify_admins,
    render_error_report,
    render_stats_report,
)
from app.storage import get_notify_users
from app.utils_openai import ai_generate

async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Рассылка «мягких напоминаний» тем, кто согласился через /notify_on.
    Дни недели фильтруем по TZ; тексты — короткие, через ChatGPT для свежести.
    """
    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    # Генерим короткий совет (3–4 строки)
    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )
    text = await ai_generate(prompt)
    if not text or text.startswith("⚠️"):
        text = "Микро-челлендж дня:\n☑️ Сон 7–9 часов\n☑️ 10 мин утреннего света\n☑️ 30 мин быстрой ходьбы"

    # Рассылаем тем, кто согласился на напоминания
    notify_users = await get_notify_users()
    delivered = 0
    for uid, user_tz in notify_users:
        if user_tz and user_tz != tz_name:
            continue
        try:
            await bot.send_message(uid, text)
            delivered += 1
        except Exception:
            # молча пропускаем закрытые чаты/блок
            pass
    preview_raw = text.replace("\n", " ")
    preview = preview_raw[:120]
    if len(preview_raw) > 120:
        preview += "…"
    preview_safe = escape(preview)
    await notify_admins(
        "📢 Рассылка выполнена\n"
        f"Получателей: {delivered}\n"
        f"Тема: {preview_safe}",
        bot=bot,
        silent=delivered == 0,
        event_kind="broadcast",
        event_payload={"recipients": delivered, "preview": preview_raw},
    )


async def send_daily_admin_report(bot: Bot, window_hours: int = 24) -> None:
    stats, errors = await asyncio.gather(
        collect_daily_stats(window_hours),
        render_error_report(window_hours=window_hours, limit=5),
    )
    report = render_stats_report(stats)
    message = f"{report}\n\n{errors}"
    await notify_admins(
        message,
        bot=bot,
        silent=True,
        event_kind="daily_report",
        event_payload={"window_hours": window_hours},
    )
