# app/scheduler/jobs.py
import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import func, or_, select

from app.db.models import Event, Subscription
from app.db.session import session_scope
from app.repo import events as events_repo
from app.services.daily_tip import dispatch_due_tips
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


async def send_daily_tips(bot: Bot) -> None:
    await dispatch_due_tips(bot)


async def _start_followup_candidates(session, cutoff: dt.datetime) -> list[int]:
    latest_start = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "start", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_quiz = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "quiz_finish", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_nudge = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "retention_test_nudge", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )

    stmt = (
        select(latest_start.c.user_id)
        .outerjoin(latest_quiz, latest_quiz.c.user_id == latest_start.c.user_id)
        .outerjoin(latest_nudge, latest_nudge.c.user_id == latest_start.c.user_id)
        .where(
            latest_start.c.ts <= cutoff,
            or_(
                latest_quiz.c.ts.is_(None),
                latest_quiz.c.ts < latest_start.c.ts,
            ),
            or_(
                latest_nudge.c.ts.is_(None),
                latest_nudge.c.ts < latest_start.c.ts,
            ),
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0] is not None]


async def _premium_followup_candidates(
    session, cutoff: dt.datetime, now: dt.datetime
) -> list[int]:
    latest_quiz = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "quiz_finish", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_nudge = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "retention_premium_nudge", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    active_subs = (
        select(Subscription.user_id)
        .where(Subscription.until > now)
        .subquery()
    )

    stmt = (
        select(latest_quiz.c.user_id)
        .outerjoin(active_subs, active_subs.c.user_id == latest_quiz.c.user_id)
        .outerjoin(latest_nudge, latest_nudge.c.user_id == latest_quiz.c.user_id)
        .where(
            latest_quiz.c.ts <= cutoff,
            active_subs.c.user_id.is_(None),
            or_(
                latest_nudge.c.ts.is_(None),
                latest_nudge.c.ts < latest_quiz.c.ts,
            ),
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0] is not None]


async def send_retention_reminders(bot: Bot) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    start_cutoff = now - dt.timedelta(hours=24)
    premium_cutoff = now - dt.timedelta(hours=72)

    async with session_scope() as session:
        start_candidates = await _start_followup_candidates(session, start_cutoff)
        premium_candidates = await _premium_followup_candidates(session, premium_cutoff, now)

    sent_start: list[int] = []
    sent_premium: list[int] = []

    for uid in start_candidates:
        try:
            await bot.send_message(uid, "⚡ Начать тест энергии")
        except Exception:
            continue
        else:
            sent_start.append(uid)

    for uid in premium_candidates:
        try:
            await bot.send_message(uid, "💎 Включи Премиум — получай подборку каждую неделю")
        except Exception:
            continue
        else:
            sent_premium.append(uid)

    if not sent_start and not sent_premium:
        return

    async with session_scope() as session:
        for uid in sent_start:
            await events_repo.log(session, uid, "retention_test_nudge", {})
        for uid in sent_premium:
            await events_repo.log(session, uid, "retention_premium_nudge", {})
        await session.commit()
