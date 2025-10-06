# app/scheduler/service.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from app.scheduler.jobs import send_nudges
from jobs.forecast_daily import send_daily_forecasts
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
    if getattr(settings, "ENABLE_PREDICTIVE_PLANNER", True):
        forecast_trigger = CronTrigger(
            hour=getattr(settings, "FORECAST_HOUR_LOCAL", 8),
            minute=getattr(settings, "FORECAST_MINUTE_LOCAL", 0),
        )
        scheduler.add_job(
            send_daily_forecasts,
            trigger=forecast_trigger,
            args=[bot],
            name="send_daily_forecasts",
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    return scheduler
