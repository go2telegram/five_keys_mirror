"""Application entry point."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, F, __version__ as aiogram_version
from aiogram.client.default import DefaultBotProperties
from aiogram.types import CallbackQuery
from aiohttp import web

from app.config import settings
from app.db.session import init_db
from app.handlers import (
    admin as h_admin,
    admin_crud as h_admin_crud,
    assistant as h_assistant,
    calc as h_calc,
    calc_kcal as h_calc_kcal,
    calc_macros as h_calc_macros,
    calc_water as h_calc_water,
    lead as h_lead,
    navigator as h_navigator,
    notify as h_notify,
    picker as h_picker,
    premium as h_premium,
    profile as h_profile,
    quiz_deficits as h_quiz_deficits,
    quiz_energy as h_quiz_energy,
    quiz_gut as h_quiz_gut,
    quiz_immunity as h_quiz_immunity,
    quiz_menu as h_quiz_menu,
    quiz_skin_joint as h_quiz_skin_joint,
    quiz_sleep as h_quiz_sleep,
    quiz_stress as h_quiz_stress,
    quiz_stress2 as h_quiz_stress2,
    referral as h_referral,
    reg as h_reg,
    report as h_report,
    start as h_start,
    subscription as h_subscription,
    tribute_webhook as h_tw,
)
from app.logging_config import setup_logging
from app.middlewares import AuditMiddleware
from app.scheduler.service import start_scheduler

try:
    from app.handlers import health as h_health
except ImportError:  # pragma: no cover - optional router
    h_health = None


log_home = logging.getLogger("home")


def _resolve_log_level(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        level = getattr(logging, str(value).upper(), logging.INFO)
        if isinstance(level, int):
            return level
    except TypeError:
        pass
    return logging.INFO


async def home_main(c: CallbackQuery) -> None:
    log_home.info(
        "HOME pressed uid=%s uname=%s",
        getattr(c.from_user, "id", None),
        getattr(c.from_user, "username", None),
    )
    try:
        from app.handlers.start import GREETING  # local import to avoid cycles
        from app.keyboards import kb_main

        if c.message is None:
            log_home.warning("home:main called without message")
            return

        try:
            await c.message.edit_text(GREETING, reply_markup=kb_main())
        except Exception:
            log_home.warning("home:main edit failed; sending fresh message", exc_info=True)
            await c.message.answer(GREETING, reply_markup=kb_main())
    except Exception:
        log_home.exception("home:main failed")
    finally:
        await c.answer()


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


def _register_audit_middleware(dp: Dispatcher) -> AuditMiddleware:
    audit_middleware = AuditMiddleware()
    dp.update.outer_middleware(audit_middleware)
    dp.message.middleware(audit_middleware)
    dp.callback_query.middleware(audit_middleware)
    logging.getLogger("startup").info("Audit middleware registered")
    return audit_middleware


async def main() -> None:
    setup_logging(
        log_dir=settings.LOG_DIR,
        level=_resolve_log_level(settings.LOG_LEVEL),
    )

    revision = await init_db()
    logging.info("current alembic version: %s", revision or "unknown")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    _register_audit_middleware(dp)
    logging.getLogger("startup").info("aiogram version: %s", aiogram_version)

    dp.include_router(h_start.router)
    dp.include_router(h_calc.router)
    dp.include_router(h_calc_water.router)
    dp.include_router(h_calc_kcal.router)
    dp.include_router(h_calc_macros.router)

    dp.include_router(h_quiz_menu.router)
    dp.include_router(h_quiz_energy.router)
    dp.include_router(h_quiz_deficits.router)
    dp.include_router(h_quiz_immunity.router)
    dp.include_router(h_quiz_gut.router)
    dp.include_router(h_quiz_sleep.router)
    dp.include_router(h_quiz_stress.router)
    dp.include_router(h_quiz_stress2.router)
    dp.include_router(h_quiz_skin_joint.router)

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

    dp.callback_query.register(home_main, F.data == "home:main")

    start_scheduler(bot)

    runner = await _setup_tribute_webhook()

    allowed_updates = dp.resolve_used_update_types()
    logging.getLogger("startup").info("allowed updates: %s", sorted(allowed_updates))
    logging.info(">>> Starting polling (aiogram)...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=allowed_updates,
        )
    finally:
        logging.info(">>> Polling stopped")
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
