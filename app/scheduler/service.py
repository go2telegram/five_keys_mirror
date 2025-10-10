import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.scheduler.jobs import (
    export_analytics_snapshot,
    process_retention_journeys,
    send_daily_tips,
    send_nudges,
    send_retention_reminders,
    send_water_reminders,
)
from app.services.weekly_ai_plan import weekly_ai_plan_job


def _parse_weekdays(csv: str | None) -> set[str]:
    # Пример: "Mon,Thu" -> {"Mon","Thu"}
    if not csv:
        return set()
    return {x.strip().title()[:3] for x in csv.split(",") if x.strip()}


def _wrap_job(
    job: Callable[..., Awaitable[Any]],
    *,
    name: str,
    logger: logging.Logger,
) -> Callable[..., Awaitable[Any]]:
    """Wrap coroutine job to log duration and swallow exceptions."""

    @wraps(job)
    async def _inner(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        logger.debug("job started", extra={"job": name})
        try:
            result = await job(*args, **kwargs)
        except Exception:
            duration = time.perf_counter() - started
            logger.exception(
                "job failed",
                extra={"job": name, "duration": duration},
            )
            return None

        duration = time.perf_counter() - started
        logger.info(
            "job finished",
            extra={"job": name, "duration": duration},
        )
        return result

    return _inner


def _schedule_job(
    scheduler: AsyncIOScheduler,
    job: Callable[..., Awaitable[Any]],
    *,
    name: str,
    trigger: CronTrigger | IntervalTrigger,
    args: list[Any] | None = None,
    misfire_grace_time: int | None = None,
) -> None:
    logger = logging.getLogger("scheduler")
    wrapped = _wrap_job(job, name=name, logger=logger)
    scheduler.add_job(
        wrapped,
        trigger=trigger,
        args=args or [],
        name=name,
        misfire_grace_time=misfire_grace_time,
    )


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Поднимаем APScheduler и запускаем джобу рассылки по расписанию.
    """
    scheduler = AsyncIOScheduler(
        timezone=settings.TIMEZONE,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        },
    )
    weekdays = _parse_weekdays(getattr(settings, "NOTIFY_WEEKDAYS", ""))

    # Каждый день в NOTIFY_HOUR_LOCAL (локальное TZ); фильтр по weekday внутри job
    if getattr(settings, "SCHEDULER_ENABLE_NUDGES", True):
        trigger = CronTrigger(hour=settings.NOTIFY_HOUR_LOCAL, minute=0)
        _schedule_job(
            scheduler,
            send_nudges,
            name="send_nudges",
            trigger=trigger,
            args=[bot, settings.TIMEZONE, weekdays],
            misfire_grace_time=600,
        )

    _schedule_job(
        scheduler,
        send_daily_tips,
        name="daily_tips",
        trigger=IntervalTrigger(minutes=5),
        args=[bot],
        misfire_grace_time=300,
    )

    _schedule_job(
        scheduler,
        send_water_reminders,
        name="water_reminders",
        trigger=IntervalTrigger(minutes=10),
        args=[bot],
        misfire_grace_time=300,
    )

    _schedule_job(
        scheduler,
        _log_heartbeat,
        name="heartbeat",
        trigger=IntervalTrigger(seconds=60),
        misfire_grace_time=30,
    )

    if getattr(settings, "WEEKLY_PLAN_ENABLED", True):
        try:
            weekly_trigger = _parse_weekly_spec(getattr(settings, "WEEKLY_PLAN_CRON", ""))
        except ValueError:
            logging.getLogger("scheduler").warning(
                "invalid WEEKLY_PLAN_CRON, falling back to Monday 10:00"
            )
            weekly_trigger = CronTrigger(day_of_week="mon", hour=10, minute=0)
        _schedule_job(
            scheduler,
            weekly_ai_plan_job,
            name="weekly_ai_plan",
            trigger=weekly_trigger,
            args=[bot, None],
            misfire_grace_time=900,
        )

    if getattr(settings, "RETENTION_ENABLED", False):
        _schedule_job(
            scheduler,
            send_retention_reminders,
            name="retention_followups",
            trigger=IntervalTrigger(hours=1),
            args=[bot],
            misfire_grace_time=300,
        )

        _schedule_job(
            scheduler,
            process_retention_journeys,
            name="retention_journeys",
            trigger=IntervalTrigger(minutes=10),
            args=[bot],
            misfire_grace_time=300,
        )

    if getattr(settings, "ANALYTICS_EXPORT_ENABLED", True):
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

        _schedule_job(
            scheduler,
            export_analytics_snapshot,
            name="analytics_export",
            trigger=analytics_trigger,
            misfire_grace_time=900,
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
