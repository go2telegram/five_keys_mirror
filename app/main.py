import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web
import os

from app.config import settings
from app.scheduler.service import start_scheduler

from policy import get_policy_engine

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

from bot import admin_policy as h_admin_policy


async def main():
    bot = Bot(token=settings.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    policy_engine = get_policy_engine()
    policy_engine.set_enabled(settings.ENABLE_META_POLICY_AI)

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
    dp.include_router(h_admin_policy.router)

    start_scheduler(bot)

    # aiohttp сервер для Tribute
    app_web = web.Application()
    app_web.router.add_post(
        settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)

    async def ping(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def version(_request: web.Request) -> web.Response:
        version = os.getenv("APP_VERSION", "dev")
        return web.json_response({"version": version})

    async def metrics(_request: web.Request) -> web.Response:
        payload = {"status": "ok"}
        if settings.ENABLE_META_POLICY_AI:
            payload.update({
                "policy_enabled": True,
                "policy": policy_engine.get_status(),
            })
        else:
            payload["policy_enabled"] = False
        return web.json_response(payload)

    async def policy_status_handler(_request: web.Request) -> web.Response:
        if not settings.ENABLE_META_POLICY_AI:
            return web.json_response(
                {"enabled": False, "message": "Meta policy AI disabled"},
                status=503,
            )
        return web.json_response(policy_engine.get_status())

    async def update_metrics(request: web.Request) -> web.Response:
        if not settings.ENABLE_META_POLICY_AI:
            return web.json_response(
                {"enabled": False, "message": "Meta policy AI disabled"},
                status=503,
            )

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        metrics_payload = payload.get("metrics") if isinstance(payload, dict) else None
        if metrics_payload is None and isinstance(payload, dict):
            metrics_payload = {k: v for k, v in payload.items() if isinstance(k, str)}

        if not isinstance(metrics_payload, dict) or not metrics_payload:
            return web.json_response({"error": "Metrics payload is empty"}, status=400)

        status = policy_engine.update_metrics(metrics_payload, source="http")
        return web.json_response(status)

    app_web.router.add_get("/ping", ping)
    app_web.router.add_get("/version", version)
    app_web.router.add_get("/metrics", metrics)
    app_web.router.add_get("/policy_status", policy_status_handler)
    app_web.router.add_post("/metrics", update_metrics)
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
