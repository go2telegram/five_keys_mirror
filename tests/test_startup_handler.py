from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
from aiogram import Router

from app.main import _create_startup_router


class _DummyStartupLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
        if args:
            msg = msg % args
        self.messages.append(msg)

    def warning(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
        return None

    def error(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
        return None


@pytest.mark.anyio("asyncio")
async def test_startup_handler_invokes_notify(monkeypatch) -> None:  # noqa: ANN001
    dummy_logger = _DummyStartupLogger()
    original_get_logger = logging.getLogger

    def fake_get_logger(name: str | None = None):  # noqa: ANN001
        if name == "startup":
            return dummy_logger
        return original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", fake_get_logger)

    notify_mock = AsyncMock()
    monkeypatch.setattr("app.main._notify_admin_startup", notify_mock)

    router = _create_startup_router(["message", "callback_query"])
    assert isinstance(router, Router)
    assert router.startup.handlers, "startup router should register handler"

    handler = router.startup.handlers[0].callback

    class _DummyBot:  # pragma: no cover - simple stub
        pass

    await handler(_DummyBot())

    assert any("startup event fired" in msg for msg in dummy_logger.messages)
    notify_mock.assert_awaited()
