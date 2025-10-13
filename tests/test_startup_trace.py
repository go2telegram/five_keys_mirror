from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Iterable

import pytest

from app import ALLOWED_UPDATES, main as main_module
from app.config import settings


class _DummyDispatcher:
    def __init__(self) -> None:
        self._routers: list[Any] = []
        self._startup_handlers: list[Any] = []
        self._update_middlewares: list[Any] = []
        self._message_middlewares: list[Any] = []
        self._callback_middlewares: list[Any] = []
        self.update = SimpleNamespace(outer_middleware=self._register_update_middleware)
        self.message = SimpleNamespace(middleware=self._register_message_middleware)
        self.callback_query = SimpleNamespace(
            middleware=self._register_callback_middleware,
            register=self._register_callback_handler,
        )

    def _register_update_middleware(self, middleware: Any) -> None:
        self._update_middlewares.append(middleware)

    def _register_message_middleware(self, middleware: Any) -> None:
        self._message_middlewares.append(middleware)

    def _register_callback_middleware(self, middleware: Any) -> None:
        self._callback_middlewares.append(middleware)

    def _register_callback_handler(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def include_router(self, router: Any) -> None:
        self._routers.append(router)
        startup = getattr(router, "startup", None)
        handlers = getattr(startup, "handlers", None)
        if handlers:
            self._startup_handlers.extend(handlers)

    def resolve_used_update_types(self) -> Iterable[str]:
        return set(ALLOWED_UPDATES)

    async def start_polling(self, bot: Any, allowed_updates: Iterable[str]) -> None:
        for handler in self._startup_handlers:
            await handler.callback(bot)


class _DummyBot:
    def __init__(self, token: str, default: Any = None, *, session: Any | None = None) -> None:
        self.token = token
        self.default = default
        self.session = session


@pytest.mark.anyio("asyncio")
async def test_startup_trace(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SERVICE_HOST", "127.0.0.1")
    monkeypatch.setenv("HEALTH_PORT", "0")
    monkeypatch.setattr(settings, "BOT_TOKEN", "TEST:FAKE", raising=False)
    monkeypatch.setattr(settings, "DEBUG_COMMANDS", False, raising=False)
    monkeypatch.setattr(settings, "SERVICE_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(settings, "HEALTH_PORT", 0, raising=False)

    def fake_setup_logging(*_args: Any, **_kwargs: Any) -> None:
        logging.getLogger("startup").info("setup_logging stub invoked")

    async def fake_init_db() -> str:
        return "rev"

    async def fake_setup_webhook() -> None:
        return None

    async def fake_start_background_queue(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_stop_background_queue() -> None:
        return None

    monkeypatch.setattr(main_module, "setup_logging", fake_setup_logging)
    monkeypatch.setattr(main_module, "init_db", fake_init_db)
    monkeypatch.setattr(main_module, "start_scheduler", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "_setup_tribute_webhook", fake_setup_webhook)
    monkeypatch.setattr(main_module, "start_background_queue", fake_start_background_queue)
    monkeypatch.setattr(main_module, "stop_background_queue", fake_stop_background_queue)
    monkeypatch.setattr(main_module, "Bot", _DummyBot)
    monkeypatch.setattr(main_module, "Dispatcher", _DummyDispatcher)

    with caplog.at_level(logging.INFO, logger="startup"):
        await main_module.main()

    text = "\n".join(record.message for record in caplog.records if record.name == "startup")
    for marker in [
        "S0:",
        "S1:",
        "S2-start:",
        "S2-done:",
        "S3:",
        "S4:",
        "S5:",
        "S6:",
        "S7:",
        "S8:",
        "S9:",
    ]:
        assert marker in text
