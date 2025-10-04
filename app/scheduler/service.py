# app/scheduler/service.py
import asyncio
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.scheduler.jobs import send_nudges


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
    scheduler.start()
    return scheduler


async def _log_heartbeat() -> None:
    """Periodically log a heartbeat message to confirm the loop is alive."""

    loop = asyncio.get_running_loop()
    pending = sum(1 for task in asyncio.all_tasks(loop) if not task.done())
    logging.getLogger("heartbeat").info("heartbeat alive tz=%s pending_tasks=%s", settings.TIMEZONE, pending)
