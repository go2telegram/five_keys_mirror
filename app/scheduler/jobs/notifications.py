"""Broadcast-style scheduled jobs."""
import datetime as dt
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.notifications import notify_admins
from app.storage import get_notify_users
from app.utils_openai import ai_generate


async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]) -> None:
    """Send motivational reminders to subscribed users."""
    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )
    text = await ai_generate(prompt)
    if not text or text.startswith("⚠️"):
        text = (
            "Микро-челлендж дня:\n"
            "☑️ Сон 7–9 часов\n"
            "☑️ 10 мин утреннего света\n"
            "☑️ 30 мин быстрой ходьбы"
        )

    notify_users = await get_notify_users()
    delivered = 0
    for uid, user_tz in notify_users:
        if user_tz and user_tz != tz_name:
            continue
        try:
            await bot.send_message(uid, text)
            delivered += 1
        except Exception:
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
