# app/scheduler/service.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot
from app.scheduler.jobs import send_nudges
from jobs.config_optimize import run_config_optimizer
from app.config import settings

def _parse_weekdays(csv: str | None) -> set[str]:
    # Пример: "Mon,Thu" -> {"Mon","Thu"}
    if not csv:
        return set()
    return {x.strip().title()[:3] for x in csv.split(",") if x.strip()}

def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Поднимаем APScheduler и запускаем джобу рассылки по расписанию.
    """
    scheduler = AsyncIOScheduler(timezone=settings.TZ)
    weekdays = _parse_weekdays(getattr(settings, "NOTIFY_WEEKDAYS", ""))

    # Каждый день в NOTIFY_HOUR_LOCAL (локальное TZ); фильтр по weekday внутри job
    trigger = CronTrigger(hour=settings.NOTIFY_HOUR_LOCAL, minute=0)
    scheduler.add_job(
        send_nudges,
        trigger=trigger,
        args=[bot, settings.TZ, weekdays],
        name="send_nudges",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )
    if settings.ENABLE_SELF_OPTIMIZATION:
        interval = max(5, getattr(settings, "OPTIMIZER_INTERVAL_SECONDS", 300))
        scheduler.add_job(
            run_config_optimizer,
            trigger=IntervalTrigger(seconds=interval),
            name="run_config_optimizer",
            misfire_grace_time=interval,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    return scheduler
