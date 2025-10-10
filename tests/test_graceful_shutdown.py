import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app import main as main_module
from app.config import settings
import app.storage_redis as storage_redis


class DummyShutdownManager:
    last_instance: "DummyShutdownManager | None" = None

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.event = asyncio.Event()
        self.closed = False
        DummyShutdownManager.last_instance = self

    def install(self) -> None:  # pragma: no cover - nothing to do in tests
        return None

    def close(self) -> None:
        self.closed = True

    def trigger(self, reason: str = "manual") -> None:
        if not self.event.is_set():
            self.logger.info("shutdown requested reason=%s", reason)
            self.event.set()

    async def wait(self) -> None:
        await self.event.wait()

    def is_set(self) -> bool:
        return self.event.is_set()


class DummyDispatcher:
    last_instance: "DummyDispatcher | None" = None

    def __init__(self) -> None:
        DummyDispatcher.last_instance = self
        self._routers: list[object] = []
        self._startup_handlers: list[object] = []
        self._update_middlewares: list[object] = []
        self._message_middlewares: list[object] = []
        self._callback_middlewares: list[object] = []
        self._stop_event: asyncio.Event | None = None
        self._stopped_event: asyncio.Event | None = None
        self.stop_called = False
        self.update = SimpleNamespace(outer_middleware=self._register_update_middleware)
        self.message = SimpleNamespace(middleware=self._register_message_middleware)
        self.callback_query = SimpleNamespace(
            middleware=self._register_callback_middleware,
            register=self._register_callback_handler,
        )

    def _register_update_middleware(self, middleware: object) -> None:
        self._update_middlewares.append(middleware)

    def _register_message_middleware(self, middleware: object) -> None:
        self._message_middlewares.append(middleware)

    def _register_callback_middleware(self, middleware: object) -> None:
        self._callback_middlewares.append(middleware)

    def _register_callback_handler(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def include_router(self, router: object) -> None:
        self._routers.append(router)
        startup = getattr(router, "startup", None)
        handlers = getattr(startup, "handlers", None)
        if handlers:
            self._startup_handlers.extend(handlers)

    def resolve_used_update_types(self) -> set[str]:
        return set(main_module.ALLOWED_UPDATES)

    async def start_polling(self, bot: object, *_, **__: Any) -> None:
        self._stop_event = asyncio.Event()
        self._stopped_event = asyncio.Event()
        for handler in self._startup_handlers:
            await handler.callback(bot)
        await self._stop_event.wait()
        self._stopped_event.set()

    async def stop_polling(self) -> None:
        self.stop_called = True
        if self._stop_event is not None:
            self._stop_event.set()
        if self._stopped_event is not None:
            await self._stopped_event.wait()


class DummySession:
    async def close(self) -> None:
        return None


class DummyBot:
    def __init__(self, token: str, default: object | None = None) -> None:
        self.token = token
        self.default = default
        self.session = DummySession()


class DummyScheduler:
    def __init__(self) -> None:
        self.shutdown_calls: list[bool] = []

    async def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


@pytest.mark.anyio("asyncio")
async def test_main_graceful_shutdown(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("SERVICE_HOST", "127.0.0.1")
    monkeypatch.setenv("HEALTH_PORT", "0")
    monkeypatch.setattr(settings, "BOT_TOKEN", "TEST:FAKE", raising=False)
    monkeypatch.setattr(settings, "DEV_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "DEBUG_COMMANDS", False, raising=False)
    monkeypatch.setattr(settings, "DASHBOARD_ENABLED", False, raising=False)

    monkeypatch.setattr(main_module, "ShutdownManager", DummyShutdownManager)
    monkeypatch.setattr(main_module, "Dispatcher", DummyDispatcher)
    monkeypatch.setattr(main_module, "Bot", DummyBot)

    async def fake_feature_flags_init() -> None:
        return None

    monkeypatch.setattr(main_module.feature_flags, "initialize", fake_feature_flags_init)
    monkeypatch.setattr(main_module.feature_flags, "environment", lambda: "test")
    monkeypatch.setattr(main_module.feature_flags, "snapshot", lambda: {"flag": True})

    async def fake_init_db() -> str:
        return "rev"

    monkeypatch.setattr(main_module, "init_db", fake_init_db)
    monkeypatch.setattr(main_module, "setup_logging", lambda *_, **__: None)
    monkeypatch.setattr(main_module, "capture_router_map", lambda _routers: None)

    background_started: dict[str, bool] = {"value": False}

    async def fake_start_background_queue(*_args, **_kwargs):
        background_started["value"] = True
        return None

    stop_calls: list[None] = []

    async def fake_stop_background_queue() -> None:
        stop_calls.append(None)

    monkeypatch.setattr(main_module, "start_background_queue", fake_start_background_queue)
    monkeypatch.setattr(main_module, "stop_background_queue", fake_stop_background_queue)

    cleanup_calls: list[tuple[object | None, object | None]] = []

    async def fake_cleanup(runner: object | None, site: object | None) -> None:
        cleanup_calls.append((runner, site))

    monkeypatch.setattr(main_module, "_cleanup_service_resources", fake_cleanup)
    monkeypatch.setattr(main_module, "_setup_service_app", lambda: asyncio.sleep(0, result=(None, None)))
    monkeypatch.setattr(main_module, "_start_dashboard_server", lambda: asyncio.sleep(0, result=(None, None)))

    scheduler = DummyScheduler()
    monkeypatch.setattr(main_module, "start_scheduler", lambda _bot: scheduler)

    close_calls: list[None] = []

    async def fake_storage_close() -> None:
        close_calls.append(None)

    monkeypatch.setattr(storage_redis, "close", fake_storage_close)

    with caplog.at_level(logging.INFO, logger="startup"):
        task = asyncio.create_task(main_module.main())
        await asyncio.sleep(0)
        shutdown = DummyShutdownManager.last_instance
        assert shutdown is not None
        shutdown.trigger("test-signal")
        await task

    dispatcher = DummyDispatcher.last_instance
    assert dispatcher is not None
    assert dispatcher.stop_called is True

    assert scheduler.shutdown_calls == [False]
    assert background_started["value"] is True
    assert stop_calls == [None]
    assert cleanup_calls == [(None, None)]
    assert close_calls == [None]

    logs = "\n".join(record.message for record in caplog.records if record.name == "startup")
    assert "shutdown complete" in logs
