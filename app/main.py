"""Application entry point."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import importlib
import logging
import time
from pathlib import Path
from typing import Iterable
from aiogram import Bot, Dispatcher, F, Router, __version__ as aiogram_version
from aiogram.client.default import DefaultBotProperties
from aiogram.types import CallbackQuery
from aiohttp import web

from app import build_info
from app.config import settings
from app.db.session import init_db, session_scope
from app.catalog import handlers as h_catalog
from app.handlers import (
    admin as h_admin,
    admin_crud as h_admin_crud,
    assistant as h_assistant,
    calc as h_calc,
    calc_unified as h_calc_unified,
    lead as h_lead,
    navigator as h_navigator,
    notify as h_notify,
    picker as h_picker,
    premium as h_premium,
    premium_center as h_premium_center,
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
from app.quiz import handlers as quiz_engine_handlers
from app.logging_config import setup_logging
from app.middlewares import AuditMiddleware
from app.repo import events as events_repo
from app.scheduler.service import start_scheduler
from app.utils import safe_edit_text

try:
    from app.handlers import health as h_health
except ImportError:  # pragma: no cover - optional router
    h_health = None


ALLOWED_UPDATES = ["message", "callback_query"]


log_home = logging.getLogger("home")
startup_log = logging.getLogger("startup")

SERVICE_START_TS = time.time()

_sentry_spec = importlib.util.find_spec("sentry_sdk")
if _sentry_spec is not None:
    sentry_sdk = importlib.import_module("sentry_sdk")
    from sentry_sdk.integrations.aiohttp import AioHttpIntegration  # type: ignore[attr-defined]
else:  # pragma: no cover - optional dependency
    sentry_sdk = None
    AioHttpIntegration = None  # type: ignore[assignment]


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


def _init_sentry() -> None:
    if sentry_sdk is None or AioHttpIntegration is None:
        logging.getLogger("startup").info("sentry disabled: library not installed")
        return

    dsn = settings.SENTRY_DSN
    if not dsn:
        return

    integrations = [AioHttpIntegration()]
    init_kwargs: dict[str, object] = {
        "dsn": dsn,
        "integrations": integrations,
        "traces_sample_rate": settings.SENTRY_TRACES_SAMPLE_RATE,
    }

    environment = getattr(settings, "ENVIRONMENT", None)
    if environment:
        init_kwargs["environment"] = environment

    release = getattr(build_info, "GIT_COMMIT", None)
    if release and release != "unknown":
        init_kwargs["release"] = release

    sentry_sdk.init(**init_kwargs)


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
            await safe_edit_text(c.message, GREETING, kb_main())
        except Exception:
            log_home.warning("home:main edit failed; sending fresh message", exc_info=True)
            await c.message.answer(GREETING, reply_markup=kb_main())
    except Exception:
        log_home.exception("home:main failed")
    finally:
        await c.answer()


async def _handle_ping(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _handle_metrics(_: web.Request) -> web.Response:
    uptime = max(0.0, time.time() - SERVICE_START_TS)
    lines = [
        "# HELP five_keys_bot_uptime_seconds Application uptime in seconds",
        "# TYPE five_keys_bot_uptime_seconds gauge",
        f"five_keys_bot_uptime_seconds {uptime:.0f}",
    ]
    branch = getattr(build_info, "GIT_BRANCH", "unknown")
    commit = getattr(build_info, "GIT_COMMIT", "unknown")
    lines.append(f'five_keys_bot_build_info{{branch="{branch}",commit="{commit}"}} 1')

    recommend_total: int | None = None
    quiz_total: int | None = None
    metrics_log = logging.getLogger("metrics")
    try:
        async with session_scope() as session:
            recommend_total = await events_repo.stats(session, name="plan_generated")
            quiz_total = await events_repo.stats(session, name="quiz_finish")
    except Exception:
        metrics_log.exception("metrics counters fetch failed")

    lines.extend(
        [
            "# HELP five_keys_bot_recommend_requests_total Total recommendation plans generated",
            "# TYPE five_keys_bot_recommend_requests_total counter",
            f"five_keys_bot_recommend_requests_total {recommend_total if recommend_total is not None else 'nan'}",
            "# HELP five_keys_bot_quiz_completed_total Total completed quizzes",
            "# TYPE five_keys_bot_quiz_completed_total counter",
            f"five_keys_bot_quiz_completed_total {quiz_total if quiz_total is not None else 'nan'}",
        ]
    )
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")


async def _setup_service_app() -> tuple[web.AppRunner, web.BaseSite]:
    app_web = web.Application()
    app_web.router.add_get("/ping", _handle_ping)
    app_web.router.add_get("/metrics", _handle_metrics)
    if settings.RUN_TRIBUTE_WEBHOOK:
        app_web.router.add_post(settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)

    runner = web.AppRunner(app_web)
    await runner.setup()
    host = settings.SERVICE_HOST
    port = settings.HEALTH_PORT
    log = logging.getLogger("startup")

    bound_host = host
    bound_port = port

    async def _start(site: web.TCPSite) -> web.BaseSite:
        nonlocal bound_host, bound_port
        await site.start()
        server = getattr(site, "_server", None)
        sockets = getattr(server, "sockets", None)
        if sockets:
            sock = next(iter(sockets))
            bound_host, bound_port = sock.getsockname()[:2]
            log.info("service bound to %s:%s", bound_host, bound_port)
        else:  # pragma: no cover - defensive branch
            log.info("service started without socket info")
        return site

    try:
        site = web.TCPSite(runner, host=host, port=port)
        await _start(site)
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.EADDRINUSE, 10048) and port != 0:
            log.warning("port %s busy, retry with ephemeral 0", port)
            site = web.TCPSite(runner, host=host, port=0)
            await _start(site)
        else:
            raise

    log.info(
        "Service server at http://%s:%s (webhook=%s)",
        bound_host,
        bound_port,
        settings.TRIBUTE_WEBHOOK_PATH if settings.RUN_TRIBUTE_WEBHOOK else "disabled",
    )
    return runner, site


async def _setup_tribute_webhook() -> web.AppRunner:
    startup_log.warning("_setup_tribute_webhook is deprecated; using _setup_service_app instead")
    runner, _site = await _setup_service_app()
    return runner


async def _start_dashboard_server() -> tuple[object | None, asyncio.Task | None]:
    if not settings.DASHBOARD_ENABLED:
        return None, None
    if not settings.DASHBOARD_TOKEN:
        logging.getLogger("startup").info("dashboard disabled: DASHBOARD_TOKEN is not configured")
        return None, None

    uvicorn_spec = importlib.util.find_spec("uvicorn")
    if uvicorn_spec is None:
        logging.getLogger("startup").info("dashboard disabled: uvicorn is not installed")
        return None, None
    uvicorn_module = importlib.import_module("uvicorn")

    try:
        from app.dashboard import app as dashboard_app
    except ImportError:
        logging.getLogger("startup").exception("dashboard import failed")
        return None, None

    config = uvicorn_module.Config(
        dashboard_app,
        host=settings.DASHBOARD_HOST,
        port=settings.DASHBOARD_PORT,
        loop="asyncio",
        log_level="info",
        access_log=False,
    )
    server = uvicorn_module.Server(config)
    task = asyncio.create_task(server.serve())
    started = getattr(server, "started", None)
    if isinstance(started, asyncio.Event):
        await started.wait()
    else:  # pragma: no cover - fallback for older uvicorn
        await asyncio.sleep(0)
    logging.getLogger("startup").info(
        "dashboard server running at http://%s:%s/admin/dashboard",
        settings.DASHBOARD_HOST,
        settings.DASHBOARD_PORT,
    )
    return server, task


def _register_audit_middleware(dp: Dispatcher) -> AuditMiddleware:
    """Register the audit middleware on every dispatcher layer."""

    audit_middleware = AuditMiddleware()
    dp.update.outer_middleware(audit_middleware)
    dp.message.middleware(audit_middleware)
    dp.callback_query.middleware(audit_middleware)
    startup_log.info("S4: audit middleware registered")
    return audit_middleware


def _log_startup_metadata() -> None:
    startup_log.info(
        "build: branch=%s commit=%s time=%s",
        getattr(build_info, "GIT_BRANCH", "unknown"),
        getattr(build_info, "GIT_COMMIT", "unknown"),
        getattr(build_info, "BUILD_TIME", "unknown"),
    )
    startup_log.info("cwd: %s", Path.cwd())
    log_dir_path = Path(settings.LOG_DIR).resolve()
    startup_log.info(
        "log_paths dir=%s bot=%s errors=%s",
        log_dir_path,
        (log_dir_path / "bot.log").resolve(),
        (log_dir_path / "errors.log").resolve(),
    )
    startup_log.info("log_config dir_param=%s level_param=%s", settings.LOG_DIR, settings.LOG_LEVEL)
    startup_log.info("aiogram=%s", aiogram_version)


def _log_router_overview(dp: Dispatcher, routers: list, allowed_updates: Iterable[str]) -> None:
    router_names = [router.name or router.__class__.__name__ for router in routers]
    startup_log.info("S5: routers attached count=%s names=%s", len(router_names), router_names)
    resolved_updates = sorted(dp.resolve_used_update_types())
    startup_log.info("resolve_used_update_types=%s", resolved_updates)


def _create_startup_router(allowed_updates: Iterable[str]) -> Router:
    startup_router = Router(name="startup")

    @startup_router.startup()
    async def on_startup(bot: Bot) -> None:  # pragma: no cover - covered via unit test
        startup_log.info("S0: startup event fired")
        await _notify_admin_startup(bot, allowed_updates)

    return startup_router


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
    _init_sentry()
    setup_logging(
        log_dir=settings.LOG_DIR,
        level=_resolve_log_level(settings.LOG_LEVEL),
    )

    t0 = time.perf_counter()

    def mark(tag: str) -> None:
        startup_log.info("%s (%.1f ms)", tag, (time.perf_counter() - t0) * 1000)

    mark("S1: setup_logging done")

    mark("S2-start: init_db")
    revision: str | None = None
    try:
        revision = await init_db()
    except Exception:
        startup_log.exception("E!: init_db failed")
    finally:
        mark("S2-done: init_db")
        logging.info("current alembic version: %s", revision or "unknown")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    mark("S3: bot/dispatcher created")

    _register_audit_middleware(dp)
    mark("S4: audit middleware registered")
    _log_startup_metadata()

    allowed_updates = list(ALLOWED_UPDATES)

    routers = [
        h_start.router,
        h_catalog.router,
        h_calc.router,
        h_calc_unified.router,
        h_quiz_menu.router,
        quiz_engine_handlers.router,
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
        h_premium_center.router,
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

    if settings.DEBUG_COMMANDS:
        from app.handlers import _echo_debug as h_echo

        routers.append(h_echo.router)
        startup_log.info("S5b: echo_debug router attached")

    startup_router = _create_startup_router(allowed_updates)
    routers.insert(0, startup_router)

    for router in routers:
        dp.include_router(router)

    dp.callback_query.register(home_main, F.data == "home:main")

    _log_router_overview(dp, routers, allowed_updates)
    mark(f"S5: routers attached count={len(routers)}")

    mark(f"S6: allowed_updates={allowed_updates}")

    start_scheduler(bot)

    runner: web.AppRunner | None = None
    site: web.BaseSite | None = None
    runner, site = await _setup_service_app()
    dashboard_server: object | None = None
    dashboard_task: asyncio.Task | None = None
    try:
        dashboard_server, dashboard_task = await _start_dashboard_server()
    except Exception:
        startup_log.exception("dashboard startup failed")
    else:
        if dashboard_task is None:
            mark("S7a: dashboard skipped")
            startup_log.info("dashboard not started (disabled)")
        else:
            mark("S7a: dashboard server started")

    mark("S7: start_polling enter")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=allowed_updates,
        )
        mark("S8: start_polling exited normally")
    except Exception:
        startup_log.exception("E!: start_polling crashed")
        raise
    finally:
        mark("S9: shutdown sequence")
        logging.info(">>> Polling stopped")
        if site is not None:
            await site.stop()
        if runner is not None:
            await runner.cleanup()
        if dashboard_server is not None and hasattr(dashboard_server, "should_exit"):
            dashboard_server.should_exit = True
        if dashboard_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await dashboard_task


if __name__ == "__main__":
    asyncio.run(main())
