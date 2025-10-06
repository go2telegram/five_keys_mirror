# app/scheduler/service.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot
from app.scheduler.jobs import send_nudges
from app.config import settings
from jobs.knowledge_sync import sync_global_knowledge
from knowledge.sync import is_enabled as knowledge_sync_enabled

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

    if knowledge_sync_enabled():
        interval_minutes = max(1, int(getattr(settings, "GLOBAL_KNOWLEDGE_SYNC_INTERVAL_MINUTES", 5)))
        scheduler.add_job(
            sync_global_knowledge,
            trigger=IntervalTrigger(minutes=interval_minutes),
            name="global_knowledge_sync",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    return scheduler
