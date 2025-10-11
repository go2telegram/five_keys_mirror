from __future__ import annotations

import logging

import pytest
from aiogram import Dispatcher, Router

from app import ALLOWED_UPDATES, build_info
from app.main import _log_router_overview, _log_startup_metadata, _register_audit_middleware
from app.middlewares import AuditMiddleware


def test_register_audit_logs_marker(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:  # noqa: ANN001
    dp = Dispatcher()

    with caplog.at_level(logging.INFO, logger="startup"):
        middleware = _register_audit_middleware(dp)
        _log_startup_metadata()
        router = Router(name="test")
        _log_router_overview(dp, [router], ALLOWED_UPDATES)

    assert isinstance(middleware, AuditMiddleware)
    messages = [record.message for record in caplog.records if record.name == "startup"]
    assert any("S4: audit middleware registered" in msg for msg in messages)
    assert any("build: version=" in msg for msg in messages)
    assert any(build_info.GIT_COMMIT in msg for msg in messages)
    assert any("log_paths dir=" in msg for msg in messages)
    assert any("aiogram=" in msg for msg in messages)
    assert any("S5: routers attached" in msg for msg in messages)
    assert any("resolve_used_update_types=" in msg for msg in messages)
