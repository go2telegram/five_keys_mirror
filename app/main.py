import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from app.config import settings
from app.db.session import init_db
from app.scheduler.service import start_scheduler

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


async def main():
    await init_db()
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

    # aiohttp сервер для Tribute
    app_web = web.Application()
    app_web.router.add_post(
        settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_HOST, port=settings.WEB_PORT)
    print(
        f"Webhook server at http://{settings.WEB_HOST}:{settings.WEB_PORT}{settings.TRIBUTE_WEBHOOK_PATH}")
    await site.start()

    print("Bot is running…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
