# app/scheduler/service.py
import asyncio
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.scheduler.jobs import (
    export_analytics_snapshot,
    send_nudges,
    send_retention_reminders,
)
from app.services.weekly_ai_plan import weekly_ai_plan_job


def _parse_weekdays(csv: str | None) -> set[str]:
    # Пример: "Mon,Thu" -> {"Mon","Thu"}
    if not csv:
        return set()
    return {x.strip().title()[:3] for x in csv.split(",") if x.strip()}


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Поднимаем APScheduler и запускаем джобу рассылки по расписанию.
    """
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
    weekdays = _parse_weekdays(getattr(settings, "NOTIFY_WEEKDAYS", ""))

    # Каждый день в NOTIFY_HOUR_LOCAL (локальное TZ); фильтр по weekday внутри job
    trigger = CronTrigger(hour=settings.NOTIFY_HOUR_LOCAL, minute=0)
    scheduler.add_job(
        send_nudges,
        trigger=trigger,
        args=[bot, settings.TIMEZONE, weekdays],
        name="send_nudges",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _log_heartbeat,
        trigger=IntervalTrigger(seconds=60),
        name="heartbeat",
        misfire_grace_time=30,
        coalesce=True,
        max_instances=1,
    )

    try:
        weekly_trigger = _parse_weekly_spec(getattr(settings, "WEEKLY_PLAN_CRON", ""))
    except ValueError:
        logging.getLogger("scheduler").warning("invalid WEEKLY_PLAN_CRON, falling back to Monday 10:00")
        weekly_trigger = CronTrigger(day_of_week="mon", hour=10, minute=0)
    scheduler.add_job(
        weekly_ai_plan_job,
        trigger=weekly_trigger,
        args=[bot, None],
        name="weekly_ai_plan",
        misfire_grace_time=900,
        coalesce=True,
        max_instances=1,
    )

    if getattr(settings, "RETENTION_ENABLED", False):
        scheduler.add_job(
            send_retention_reminders,
            trigger=IntervalTrigger(hours=1),
            args=[bot],
            name="retention_followups",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )

    analytics_cron = getattr(settings, "ANALYTICS_EXPORT_CRON", None)
    if analytics_cron:
        try:
            analytics_trigger = CronTrigger.from_crontab(
                analytics_cron, timezone=settings.TIMEZONE
            )
        except ValueError:
            logging.getLogger("scheduler").warning(
                "invalid ANALYTICS_EXPORT_CRON, falling back to 21:00"
            )
            analytics_trigger = CronTrigger(hour=21, minute=0, timezone=settings.TIMEZONE)
    else:
        analytics_trigger = CronTrigger(hour=21, minute=0, timezone=settings.TIMEZONE)

    scheduler.add_job(
        export_analytics_snapshot,
        trigger=analytics_trigger,
        name="analytics_export",
        misfire_grace_time=900,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    return scheduler


async def _log_heartbeat() -> None:
    """Periodically log a heartbeat message to confirm the loop is alive."""

    loop = asyncio.get_running_loop()
    pending = sum(1 for task in asyncio.all_tasks(loop) if not task.done())
    logging.getLogger("heartbeat").info("heartbeat alive tz=%s pending_tasks=%s", settings.TIMEZONE, pending)


def _parse_weekly_spec(spec: str | None) -> CronTrigger:
    if not spec:
        return CronTrigger(day_of_week="mon", hour=10, minute=0)
    day_part, _, time_part = spec.partition("@")
    day = day_part.strip() or "mon"
    hour = 10
    minute = 0
    time_part = time_part.strip() or "10"
    if ":" in time_part:
        hour_part, minute_part = time_part.split(":", 1)
    else:
        hour_part, minute_part = time_part, "0"
    try:
        hour = int(hour_part)
        minute = int(minute_part)
    except ValueError as exc:
        raise ValueError("invalid weekly cron time") from exc
    return CronTrigger(day_of_week=day, hour=hour, minute=minute)
