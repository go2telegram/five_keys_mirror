"""Smoke tests for dispatcher update types and module imports."""

import os
import sys
from contextlib import ExitStack
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import MagicMock, patch

from aiogram import Dispatcher
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///:memory:")


def _load_start_module():
    """Import the start handler with database objects patched out."""

    sys.modules.pop("app.handlers.start", None)
    sys.modules.pop("app.db.session", None)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=MagicMock(name="async_engine"),
            )
        )
        stack.enter_context(
            patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker",
                return_value=MagicMock(name="async_session_factory"),
            )
        )
        module = import_module("app.handlers.start")

    return module


h_start = _load_start_module()


@pytest.mark.skipif(find_spec("reportlab") is None, reason="reportlab not installed")
def test_import_main_module() -> None:
    """The application entry point should be importable without side effects."""

    module = import_module("app.main")
    assert module is not None


def test_resolve_used_update_types_contains_message_and_callback() -> None:
    """Dispatcher must subscribe to message and callback updates for /start and menus."""

    dp = Dispatcher()
    dp.include_router(h_start.router)

    updates = set(dp.resolve_used_update_types())

    assert "message" in updates
    assert "callback_query" in updates
