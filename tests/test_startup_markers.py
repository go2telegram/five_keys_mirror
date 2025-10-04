from __future__ import annotations

import logging

from aiogram import Dispatcher

from app.main import _register_audit_middleware
from app.middlewares import AuditMiddleware


class _DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
        if args:
            msg = msg % args
        self.messages.append(msg)

    def __getattr__(self, name: str):  # noqa: ANN001
        def _(*_args, **_kwargs) -> None:  # noqa: ANN001, ANN002
            return None

        return _


def test_register_audit_logs_marker(monkeypatch) -> None:  # noqa: ANN001
    dummy = _DummyLogger()
    original_get_logger = logging.getLogger

    def fake_get_logger(name: str | None = None):  # noqa: ANN001
        if name == "startup":
            return dummy
        return original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", fake_get_logger)

    dp = Dispatcher()
    middleware = _register_audit_middleware(dp)

    assert isinstance(middleware, AuditMiddleware)
    assert any("Audit middleware registered" in msg for msg in dummy.messages)
