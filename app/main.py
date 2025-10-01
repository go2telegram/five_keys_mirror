"""Application entry point."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from app.config import settings
from app.db.session import init_db
from app.handlers import (
    admin as h_admin,
    admin_crud as h_admin_crud,
    assistant as h_assistant,
    calc as h_calc,
    lead as h_lead,
    navigator as h_navigator,
    notify as h_notify,
    picker as h_picker,
    premium as h_premium,
    profile as h_profile,
    quiz_energy as h_quiz_energy,
    quiz_gut as h_quiz_gut,
    quiz_immunity as h_quiz_immunity,
    quiz_menu as h_quiz_menu,
    quiz_sleep as h_quiz_sleep,
    quiz_stress as h_quiz_stress,
    referral as h_referral,
    reg as h_reg,
    report as h_report,
    start as h_start,
    subscription as h_subscription,
    tribute_webhook as h_tw,
)
from app.scheduler.service import start_scheduler

try:
    from app.handlers import health as h_health
except ImportError:  # pragma: no cover - optional router
    h_health = None


async def _setup_tribute_webhook() -> Optional[web.AppRunner]:
    if not settings.RUN_TRIBUTE_WEBHOOK:
        logging.info("Tribute webhook server disabled (RUN_TRIBUTE_WEBHOOK=false)")
        return None

    app_web = web.Application()
    app_web.router.add_post(settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)

    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=settings.WEB_HOST,
        port=settings.TRIBUTE_PORT,
    )
    await site.start()
    logging.info(
        "Tribute webhook server at http://%s:%s%s",
        settings.WEB_HOST,
        settings.TRIBUTE_PORT,
        settings.TRIBUTE_WEBHOOK_PATH,
    )
    return runner


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    revision = await init_db()
    logging.info("current alembic version: %s", revision or "unknown")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    dp.include_router(h_start.router)
    dp.include_router(h_calc.router)

    dp.include_router(h_quiz_menu.router)
    dp.include_router(h_quiz_energy.router)
    dp.include_router(h_quiz_immunity.router)
    dp.include_router(h_quiz_gut.router)
    dp.include_router(h_quiz_sleep.router)
    dp.include_router(h_quiz_stress.router)

    dp.include_router(h_picker.router)
    dp.include_router(h_reg.router)
    dp.include_router(h_premium.router)
    dp.include_router(h_profile.router)
    dp.include_router(h_referral.router)
    dp.include_router(h_subscription.router)
    dp.include_router(h_navigator.router)
    dp.include_router(h_report.router)
    dp.include_router(h_notify.router)

    dp.include_router(h_admin.router)
    dp.include_router(h_admin_crud.router)
    dp.include_router(h_assistant.router)
    dp.include_router(h_lead.router)

    if settings.DEBUG_COMMANDS and h_health is not None:
        dp.include_router(h_health.router)

    start_scheduler(bot)

    runner = await _setup_tribute_webhook()

    logging.info(">>> Starting polling (aiogram)...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logging.info(">>> Polling stopped")
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
