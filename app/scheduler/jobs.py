# app/scheduler/jobs.py
import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.db.session import session_scope
from app.repo import events as events_repo
from app.utils_openai import ai_generate


async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Рассылка «мягких напоминаний» тем, кто согласился (последнее событие notify_on).
    Дни недели фильтруем по TZ; тексты — короткие, через ChatGPT для свежести.
    """
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
        text = "Микро-челлендж дня:\n" "☑️ Сон 7–9 часов\n" "☑️ 10 мин утреннего света\n" "☑️ 30 мин быстрой ходьбы"

    async with session_scope() as session:
        user_ids = await events_repo.notify_recipients(session)

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
        except Exception:
            continue
