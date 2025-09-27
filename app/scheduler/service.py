# app/scheduler/service.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from app.scheduler.jobs import send_nudges
from app.config import settings

def _parse_weekdays(csv: str | None) -> set[str]:
    # РџСЂРёРјРµСЂ: "Mon,Thu" -> {"Mon","Thu"}
    if not csv:
        return set()
    return {x.strip().title()[:3] for x in csv.split(",") if x.strip()}

def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    РџРѕРґРЅРёРјР°РµРј APScheduler Рё Р·Р°РїСѓСЃРєР°РµРј РґР¶РѕР±Сѓ СЂР°СЃСЃС‹Р»РєРё РїРѕ СЂР°СЃРїРёСЃР°РЅРёСЋ.
    """
    scheduler = AsyncIOScheduler(timezone=settings.TZ)
    weekdays = _parse_weekdays(getattr(settings, "NOTIFY_WEEKDAYS", ""))

    # РљР°Р¶РґС‹Р№ РґРµРЅСЊ РІ NOTIFY_HOUR_LOCAL (Р»РѕРєР°Р»СЊРЅРѕРµ TZ); С„РёР»СЊС‚СЂ РїРѕ weekday РІРЅСѓС‚СЂРё job
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
    scheduler.start()
    return scheduler

