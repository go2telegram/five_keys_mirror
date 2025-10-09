# app/scheduler/jobs.py
import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.db.session import session_scope
from app.repo import events as events_repo
from app.repo import tracker as tracker_repo
from app.services.habit_tracker import is_valid_time_slot, resolve_timezone
from app.storage import commit_safely
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


def _slot_due(now_local: dt.datetime, slot: str, window_minutes: int = 10) -> bool:
    if not is_valid_time_slot(slot):
        return False
    hour, minute = map(int, slot.split(":"))
    scheduled = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (now_local - scheduled).total_seconds()
    return 0 <= delta < window_minutes * 60


def _reminder_text(slot: str) -> str:
    return (
        f"⏰ {slot} — время проверить привычки!\n"
        "Отметь воду, сон или стресс: /track_water, /track_sleep, /track_stress.\n"
        "Прогресс: /today"
    )


async def send_habit_reminders(bot: Bot, now_utc: dt.datetime | None = None) -> None:
    """Dispatch habit reminders according to user preferences."""

    moment = now_utc or dt.datetime.now(dt.timezone.utc)
    async with session_scope() as session:
        profiles = await tracker_repo.list_reminder_profiles(session)

    due: list[tuple[int, str, dt.datetime]] = []
    for profile in profiles:
        tz = resolve_timezone(profile.timezone)
        now_local = moment.astimezone(tz)
        today_iso = now_local.date().isoformat()
        for slot in profile.times:
            if profile.last_sent.get(slot) == today_iso:
                continue
            if _slot_due(now_local, slot):
                due.append((profile.user_id, slot, now_local))

    if not due:
        return

    sent: list[tuple[int, str, str]] = []
    for user_id, slot, local_dt in due:
        try:
            await bot.send_message(user_id, _reminder_text(slot))
        except Exception:
            continue
        sent.append((user_id, slot, local_dt.date().isoformat()))

    if not sent:
        return

    async with session_scope() as session:
        await tracker_repo.mark_reminders_sent(session, sent)
        await commit_safely(session)
