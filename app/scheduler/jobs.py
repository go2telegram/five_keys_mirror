# app/scheduler/jobs.py
import datetime as dt
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select

from app.config import settings
from app.db.models import Event, Lead, Subscription
from app.db.session import session_scope
from app.repo import events as events_repo, retention as retention_repo
from app.services import retention_logic, retention_messages
from app.services.reminders import ReminderConfig, ReminderPlanner
from app.utils_openai import ai_generate

_analytics_log = logging.getLogger("scheduler.analytics")


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
        text = "Микро-челлендж дня:\n☑️ Сон 7–9 часов\n☑️ 10 мин утреннего света\n☑️ 30 мин быстрой ходьбы"

    async with session_scope() as session:
        user_ids = await events_repo.notify_recipients(session)

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
        except Exception:
            continue


async def send_daily_tips(bot: Bot) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    async with session_scope() as session:
        settings = await retention_repo.list_tip_candidates(session)
        for setting in settings:
            tz = retention_logic.ensure_timezone(setting.timezone)
            local_now = now.astimezone(tz)
            if not retention_logic.should_send_tip(local_now, setting.tips_time, setting.last_tip_sent_at):
                continue
            tip = await retention_repo.pick_tip(session, exclude_id=setting.last_tip_id)
            if tip is None:
                continue
            text = retention_messages.format_tip_message(tip.text)
            kb = InlineKeyboardBuilder()
            kb.button(text="👍 Полезно", callback_data=f"tips:like:{tip.id}")
            try:
                await bot.send_message(setting.user_id, text, reply_markup=kb.as_markup())
            except Exception:
                continue
            await retention_repo.update_tip_log(session, setting, tip=tip, sent_at=now)
            await events_repo.log(
                session,
                setting.user_id,
                "daily_tip_sent",
                {"tip_id": tip.id},
            )
        await session.commit()


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


async def _premium_followup_candidates(session, cutoff: dt.datetime, now: dt.datetime) -> list[int]:
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
    active_subs = select(Subscription.user_id).where(Subscription.until > now).subquery()

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


async def send_water_reminders(bot: Bot) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    async with session_scope() as session:
        settings = await retention_repo.list_water_candidates(session)
        for setting in settings:
            tz = retention_logic.ensure_timezone(setting.timezone)
            local_now = now.astimezone(tz)
            if setting.water_window_end <= setting.water_window_start:
                continue
            if setting.water_last_sent_date != local_now.date():
                setting.water_last_sent_date = local_now.date()
                setting.water_sent_count = 0

            weight = setting.weight_kg
            if weight is None:
                weight = await retention_repo.latest_weight_from_events(session, setting.user_id)
                await retention_repo.update_weight(session, setting, weight)

            goal_ml = retention_logic.water_goal_from_weight(weight)
            reminder_count = retention_logic.water_reminders_from_weight(weight)
            tz_label = getattr(tz, "key", str(tz))
            config = ReminderConfig(
                tz=str(tz_label),
                water_goal_ml=goal_ml,
                water_reminders=reminder_count,
                water_window_start=setting.water_window_start,
                water_window_end=setting.water_window_end,
            )
            planner = ReminderPlanner(config)
            try:
                schedule = planner.water_schedule(reference=local_now)
            except Exception:
                continue
            total_reminders = len(schedule)
            setting.water_goal_ml = goal_ml
            setting.water_reminders = total_reminders
            if total_reminders == 0:
                await retention_repo.record_water_progress(
                    session,
                    setting,
                    goal_ml=goal_ml,
                    reminders=total_reminders,
                    sent_date=local_now.date(),
                    sent_count=setting.water_sent_count,
                )
                continue

            sent_count = setting.water_sent_count or 0
            if sent_count >= total_reminders:
                continue

            next_due = schedule[sent_count]
            if local_now < next_due:
                continue

            consumed_ml = retention_logic.water_consumed(goal_ml, total_reminders, sent_count)
            message = planner.water_message(consumed_ml, goal_ml)
            try:
                await bot.send_message(setting.user_id, message)
            except Exception:
                continue

            sent_count += 1
            await retention_repo.record_water_progress(
                session,
                setting,
                goal_ml=goal_ml,
                reminders=total_reminders,
                sent_date=local_now.date(),
                sent_count=sent_count,
            )
            await events_repo.log(
                session,
                setting.user_id,
                "water_reminder_sent",
                {
                    "goal_ml": goal_ml,
                    "reminders": total_reminders,
                    "sent_count": sent_count,
                },
            )
        await session.commit()


async def process_retention_journeys(bot: Bot) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    async with session_scope() as session:
        due = await retention_repo.pending_journeys(session, now=now, limit=100)
        sent_entries: list = []
        for entry in due:
            if entry.journey == "sleep_checkin":
                text = (
                    f"{retention_messages.format_sleep_journey_message()}\n\n"
                    "📲 Включить трекер сна (/track_sleep <часы>)"
                )
                kb = InlineKeyboardBuilder()
                kb.button(text="Отлично", callback_data="journey_sleep:excellent")
                kb.button(text="Нормально", callback_data="journey_sleep:ok")
                kb.button(text="Плохо", callback_data="journey_sleep:bad")
                kb.button(text="📲 Включить трекер сна", callback_data="journey:tracker_sleep")
                kb.adjust(3, 1)
                markup = kb.as_markup()
            elif entry.journey == "stress_relief":
                text = f"{retention_messages.format_stress_journey_message()}\n\n💡 Хочу Премиум-план (/premium)"
                kb = InlineKeyboardBuilder()
                kb.button(text="Низкий", callback_data="journey_stress:low")
                kb.button(text="Средний", callback_data="journey_stress:medium")
                kb.button(text="Высокий", callback_data="journey_stress:high")
                kb.button(text="💡 Хочу Премиум-план", callback_data="journey:premium_plan")
                kb.adjust(3, 1)
                markup = kb.as_markup()
            else:
                continue

            try:
                await bot.send_message(entry.user_id, text, reply_markup=markup)
            except Exception:
                continue

            sent_entries.append(entry)
            await events_repo.log(
                session,
                entry.user_id,
                "journey_sent",
                {"journey": entry.journey},
            )

        if sent_entries:
            await retention_repo.mark_journeys_sent(session, sent_entries, sent_at=now)
        await session.commit()


async def export_analytics_snapshot() -> Path | None:
    target = getattr(settings, "ANALYTICS_EXPORT_PATH", "")
    if not target:
        _analytics_log.info("analytics export skipped: path not configured")
        return None

    export_path = Path(target)
    now = dt.datetime.now(dt.timezone.utc)
    day_ago = now - dt.timedelta(hours=24)
    week_ago = now - dt.timedelta(days=7)

    async with session_scope() as session:
        quiz_24h = await events_repo.stats(session, name="quiz_finish", since=day_ago)
        quiz_7d = await events_repo.stats(session, name="quiz_finish", since=week_ago)
        plans_24h = await events_repo.stats(session, name="plan_generated", since=day_ago)
        plans_7d = await events_repo.stats(session, name="plan_generated", since=week_ago)
        retention_test_24h = await events_repo.stats(session, name="retention_test_nudge", since=day_ago)
        retention_test_7d = await events_repo.stats(session, name="retention_test_nudge", since=week_ago)
        retention_premium_24h = await events_repo.stats(session, name="retention_premium_nudge", since=day_ago)
        retention_premium_7d = await events_repo.stats(session, name="retention_premium_nudge", since=week_ago)

        total_leads_stmt = select(func.count(Lead.id))
        total_leads = (await session.execute(total_leads_stmt)).scalar_one()
        leads_7d_stmt = select(func.count(Lead.id)).where(Lead.ts >= week_ago)
        leads_7d = (await session.execute(leads_7d_stmt)).scalar_one()

        active_subs_stmt = select(func.count(Subscription.user_id)).where(Subscription.until > now)
        active_subs = (await session.execute(active_subs_stmt)).scalar_one()
        new_subs_stmt = select(func.count(Subscription.user_id)).where(Subscription.since >= week_ago)
        new_subs = (await session.execute(new_subs_stmt)).scalar_one()

    payload = {
        "generated_at": now.isoformat(),
        "quiz_finishes": {"24h": quiz_24h, "7d": quiz_7d},
        "plans": {"24h": plans_24h, "7d": plans_7d},
        "retention": {
            "test": {"24h": retention_test_24h, "7d": retention_test_7d},
            "premium": {"24h": retention_premium_24h, "7d": retention_premium_7d},
        },
        "leads": {"total": total_leads, "7d": leads_7d},
        "premium": {"active": active_subs, "new_7d": new_subs},
    }

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _analytics_log.info("analytics snapshot exported", extra={"path": str(export_path)})
    return export_path
