from __future__ import annotations

import logging

from aiogram import Dispatcher, Router

from app import ALLOWED_UPDATES, build_info
from app.main import _log_router_overview, _log_startup_metadata, _register_audit_middleware
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

    _log_startup_metadata()

    assert any("build: branch=" in msg for msg in dummy.messages)
    assert any(build_info.GIT_COMMIT in msg for msg in dummy.messages)

    dummy.messages.clear()
    router = Router(name="test")
    _log_router_overview(dp, [router], ALLOWED_UPDATES)
    assert any("routers=['test']" in msg for msg in dummy.messages)
    assert any("allowed_updates=['message', 'callback_query']" in msg for msg in dummy.messages)
    assert any("resolve_used_update_types=" in msg for msg in dummy.messages)
