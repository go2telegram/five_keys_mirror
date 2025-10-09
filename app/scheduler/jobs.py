# app/scheduler/jobs.py
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.db.session import session_scope
from app.reco.ai_reasoner import build_ai_plan
from app.repo import events as events_repo
from app.repo import subscriptions as subscriptions_repo
from app.storage import commit_safely
from app.utils import split_md
from app.utils_openai import ai_generate


LOG = logging.getLogger(__name__)


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


async def weekly_ai_plan(bot: Bot):
    """Send the refreshed 7-day AI plan to every active premium user."""

    async with session_scope() as session:
        user_ids = await subscriptions_repo.active_user_ids(session)

    for user_id in user_ids:
        try:
            text = await build_ai_plan(user_id, "7d")
            await bot.send_message(user_id, "🆕 Твой обновлённый план на неделю готов!")
            for chunk in split_md(text, 3500):
                await bot.send_message(user_id, chunk, parse_mode="Markdown")
            async with session_scope() as session:
                await events_repo.log(session, user_id, "plan_generated", {"source": "weekly"})
                await commit_safely(session)
        except Exception:
            LOG.exception("weekly_ai_plan failed uid=%s", user_id)
