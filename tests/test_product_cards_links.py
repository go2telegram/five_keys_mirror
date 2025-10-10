from unittest.mock import AsyncMock, MagicMock

import pytest

import app.keyboards as keyboards
from app.utils.cards import send_product_cards
from app.utils.nav import nav_footer


@pytest.mark.asyncio
async def test_product_cards_use_link_manager_and_footer(monkeypatch):
    calls: list[tuple[str, dict | None, bool]] = []

    def fake_build_order_link(code: str, *, params=None, replace=False):  # type: ignore[override]
        calls.append((code, params, replace))
        params = params or {}
        utm_source = params.get("utm_source")
        utm_medium = params.get("utm_medium")
        return f"https://example.com/{code}?utm_source={utm_source}&utm_medium={utm_medium}"

    monkeypatch.setattr(keyboards, "build_order_link", fake_build_order_link)

    message = MagicMock()
    message.answer = AsyncMock()
    message.answer_media_group = AsyncMock()

    product = {
        "code": "nash-omega-3",
        "name": "Омега-3",
        "order_url": "https://legacy.example/omega",
        "props": [],
        "images": [],
        "helps_text": "",
    }

    await send_product_cards(
        message,
        "Итог",
        [product],
        back_cb="catalog:menu",
    )

    assert calls, "build_order_link should be invoked for buy buttons"
    code, params, replace = calls[0]
    assert code == "nash-omega-3"
    assert replace is False
    assert params is not None
    assert params.get("utm_source") == "tg_bot"
    assert params.get("utm_medium") == "product_cards"
    assert params.get("utm_campaign") == "product_cards"
    assert params.get("utm_content") == "nash-omega-3"

    footer_text = "🏠 Главное меню • 🧪 Тесты • 🎯 Рекомендации • 🛍 Каталог"
    footer_call = None
    for call in message.answer.call_args_list:
        if call.args and call.args[0] == footer_text:
            footer_call = call
            break

    assert footer_call is not None, "Navigation footer should be sent after cards"
    markup = footer_call.kwargs.get("reply_markup")
    assert markup is not None
    expected_markup = nav_footer()
    assert markup.inline_keyboard == expected_markup.inline_keyboard
