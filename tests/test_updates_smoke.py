"""Smoke tests for dispatcher update types and module imports."""

import asyncio
from importlib import import_module
from importlib.util import find_spec
from unittest.mock import AsyncMock, MagicMock

import pytest


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
