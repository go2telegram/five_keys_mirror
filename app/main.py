"""Application entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterable, Optional

from aiogram import Bot, Dispatcher, F, Router, __version__ as aiogram_version
from aiogram.client.default import DefaultBotProperties
from aiogram.types import CallbackQuery
from aiohttp import web

from app import ALLOWED_UPDATES, build_info
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


def _log_startup_metadata() -> None:
    startup_log = logging.getLogger("startup")
    startup_log.info(
        "build: branch=%s commit=%s time=%s",
        getattr(build_info, "GIT_BRANCH", "unknown"),
        getattr(build_info, "GIT_COMMIT", "unknown"),
        getattr(build_info, "BUILD_TIME", "unknown"),
    )
    startup_log.info("cwd: %s", Path.cwd())
    startup_log.info("log_dir=%s log_level=%s", settings.LOG_DIR, settings.LOG_LEVEL)
    startup_log.info("aiogram version: %s", aiogram_version)


def _log_router_overview(dp: Dispatcher, routers: list, allowed_updates: Iterable[str]) -> None:
    startup_log = logging.getLogger("startup")
    router_names = [router.name or router.__class__.__name__ for router in routers]
    startup_log.info("routers=%s count=%s", router_names, len(router_names))
    allowed_list = list(allowed_updates)
    startup_log.info("allowed_updates=%s", allowed_list)
    resolved_updates = sorted(dp.resolve_used_update_types())
    startup_log.info("resolve_used_update_types=%s", resolved_updates)


def _gather_admin_ids() -> set[int]:
    admins: set[int] = set()
    if settings.ADMIN_ID:
        admins.add(int(settings.ADMIN_ID))
    admins.update(int(item) for item in settings.ADMIN_USER_IDS or [])
    return {admin for admin in admins if admin}


async def _notify_admin_startup(bot: Bot, allowed_updates: Iterable[str]) -> None:
    admins = _gather_admin_ids()
    startup_log = logging.getLogger("startup")
    if not admins:
        startup_log.info("admin notification skipped: no admin ids configured")
        return

    message = (
        "\u2705 \u0411\u043e\u0442 \u0437\u0430\u043f\u0443\u0449\u0435\u043d: "
        f"branch={getattr(build_info, 'GIT_BRANCH', 'unknown')} "
        f"commit={getattr(build_info, 'GIT_COMMIT', 'unknown')} "
        f"aiogram={aiogram_version} "
        f"allowed_updates={list(allowed_updates)}"
    )

    for admin_id in sorted(admins):
        try:
            await bot.send_message(admin_id, message)
            startup_log.info("admin notified uid=%s", admin_id)
        except Exception as exc:  # pragma: no cover - network/Telegram errors
            startup_log.warning("failed to notify admin uid=%s: %s", admin_id, exc)


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
    _log_startup_metadata()

    allowed_updates = list(ALLOWED_UPDATES)

    routers = [
        h_start.router,
        h_calc.router,
        h_calc_water.router,
        h_calc_kcal.router,
        h_calc_macros.router,
        h_quiz_menu.router,
        h_quiz_energy.router,
        h_quiz_deficits.router,
        h_quiz_immunity.router,
        h_quiz_gut.router,
        h_quiz_sleep.router,
        h_quiz_stress.router,
        h_quiz_stress2.router,
        h_quiz_skin_joint.router,
        h_picker.router,
        h_reg.router,
        h_premium.router,
        h_profile.router,
        h_referral.router,
        h_subscription.router,
        h_navigator.router,
        h_report.router,
        h_notify.router,
        h_admin.router,
        h_admin_crud.router,
        h_assistant.router,
        h_lead.router,
    ]

    if settings.DEBUG_COMMANDS and h_health is not None:
        routers.append(h_health.router)

    startup_router = Router(name="startup")

    @startup_router.startup()
    async def on_startup(event: object, bot: Bot) -> None:  # noqa: ANN001
        startup_log = logging.getLogger("startup")
        startup_log.info("startup event fired")
        await _notify_admin_startup(bot, allowed_updates)

    routers.insert(0, startup_router)

    for router in routers:
        dp.include_router(router)

    dp.callback_query.register(home_main, F.data == "home:main")

    _log_router_overview(dp, routers, allowed_updates)

    start_scheduler(bot)

    runner = await _setup_tribute_webhook()
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
