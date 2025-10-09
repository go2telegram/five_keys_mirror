# app/scheduler/jobs.py
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.db.session import session_scope
from app.repo import events as events_repo, results as results_repo
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


async def cleanup_stale_results() -> None:
    """Remove quiz and calculator results older than 180 days."""

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=180)
    async with session_scope() as session:
        quiz_deleted = await results_repo.delete_quiz_results_older_than(session, cutoff)
        calc_deleted = await results_repo.delete_calculator_results_older_than(session, cutoff)
        await session.commit()

    logging.getLogger("scheduler").info(
        "cleanup_stale_results cutoff=%s quiz_deleted=%s calc_deleted=%s",
        cutoff.isoformat(),
        quiz_deleted,
        calc_deleted,
    )
