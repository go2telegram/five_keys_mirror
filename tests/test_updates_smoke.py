"""Smoke tests for dispatcher update types and module imports."""

import asyncio
import os
import sys
from contextlib import ExitStack
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Dispatcher

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


def test_send_product_cards_produces_summary_text():
    from app.handlers.quiz_common import send_product_cards

    async def _run() -> str:
        message = MagicMock()
        message.answer = AsyncMock()
        message.answer_media_group = AsyncMock()

        cards = [
            {
                "code": "T8_BLEND",
                "name": "T8 BLEND",
                "short": "Антиоксиданты и мягкая поддержка энергии.",
                "props": ["Антиоксидантная защита", "Поддержка митохондрий"],
                "images": ["https://example.com/blend.jpg"],
                "order_url": "https://example.com/order/blend",
                "helps_text": "Держит дневную энергию без скачков.",
            }
        ]

        await send_product_cards(
            message,
            "Итог: тест",
            cards,
            bullets=["Сон 7–9 часов"],
            back_cb="calc:menu",
        )

        assert message.answer.called
        return "\n".join(call.args[0] for call in message.answer.call_args_list if call.args)

    summary_text = asyncio.run(_run())
    assert "Итог: тест" in summary_text
    assert "Сон 7–9 часов" in summary_text
    assert "Поддержка" in summary_text


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


def test_start_safe_sends_greeting_even_if_full_logic_fails() -> None:
    """The /start safe handler must reply even when the heavy logic errors out."""

    class FailingScope:
        async def __aenter__(self):  # pragma: no cover - exercised in test runtime
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _run() -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        message.from_user = MagicMock(id=123, username="tester")
        message.text = "/start"

        with patch("app.handlers.start.session_scope", return_value=FailingScope()):
            await h_start.start_safe(message)
            await asyncio.sleep(0)

        message.answer.assert_called()

    asyncio.run(_run())
