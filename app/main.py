import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from app.config import settings
from app.scheduler.service import start_scheduler
from app.metrics import setup_metrics
from app.db.session import init_db_safe
from app.products import sync_products
from app.health import recovery_state, setup_healthcheck
from app.watchdog import start_watchdog

# существующие роутеры
from app.handlers import start as h_start
from app.handlers import calc as h_calc
from app.handlers import quiz_energy as h_quiz_energy
from app.handlers import quiz_immunity as h_quiz_immunity
from app.handlers import quiz_gut as h_quiz_gut
from app.handlers import quiz_sleep as h_quiz_sleep
from app.handlers import quiz_stress as h_quiz_stress
from app.handlers import quiz_menu as h_quiz_menu
from app.handlers import picker as h_picker
from app.handlers import reg as h_reg
from app.handlers import assistant as h_assistant
from app.handlers import admin as h_admin
from app.handlers import navigator as h_navigator
from app.handlers import notify as h_notify
from app.handlers import report as h_report
from app.handlers import lead as h_lead

# новые
from app.handlers import subscription as h_subscription
from app.handlers import premium as h_premium
from app.handlers import tribute_webhook as h_tw
from app.handlers import referral as h_referral


logger = logging.getLogger(__name__)


async def main():
    await init_db_safe()
    await sync_products()
    bot = Bot(token=settings.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # роутеры
    dp.include_router(h_start.router)
    dp.include_router(h_calc.router)
    dp.include_router(h_quiz_energy.router)
    dp.include_router(h_quiz_immunity.router)
    dp.include_router(h_quiz_gut.router)
    dp.include_router(h_quiz_sleep.router)
    dp.include_router(h_quiz_stress.router)
    dp.include_router(h_quiz_menu.router)
    dp.include_router(h_picker.router)
    dp.include_router(h_reg.router)
    dp.include_router(h_assistant.router)
    dp.include_router(h_admin.router)
    dp.include_router(h_navigator.router)
    dp.include_router(h_notify.router)
    dp.include_router(h_report.router)
    dp.include_router(h_lead.router)
    dp.include_router(h_subscription.router)
    dp.include_router(h_premium.router)
    dp.include_router(h_referral.router)

    start_scheduler(bot)

    # aiohttp сервер для Tribute и метрик
    app_web = web.Application()
    setup_metrics(dp, app_web)
    setup_healthcheck(app_web)
    app_web.router.add_post(
        settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_HOST, port=settings.WEB_PORT)
    print(
        f"Webhook server at http://{settings.WEB_HOST}:{settings.WEB_PORT}{settings.TRIBUTE_WEBHOOK_PATH}")
    await site.start()

    restart_event = asyncio.Event()

    async def trigger_restart(reason: str) -> None:
        if restart_event.is_set():
            return

        restart_event.set()
        await recovery_state.request(reason)
        try:
            await dp.stop_polling()
        except Exception as exc:  # noqa: BLE001 - logging for visibility
            logger.exception("Failed to stop polling during restart: %s", exc)

    ping_url = f"http://{settings.WEB_HOST}:{settings.WEB_PORT}/ping"
    watchdog_task = start_watchdog(ping_url, trigger_restart)

    print("Bot is running…")

    try:
        while True:
            try:
                await dp.start_polling(bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - restart loop on any failure
                logger.exception("Polling crashed, scheduling restart", exc_info=exc)
                await trigger_restart("polling-crash")

            if restart_event.is_set():
                await init_db_safe()
                await sync_products()
                await recovery_state.mark_recovered()
                restart_event.clear()
                continue

            break
    finally:
        watchdog_task.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog_task
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
