import asyncio

import pytest

pytest.importorskip("aiosqlite")

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.handlers import notify, picker, premium, referral, subscription
from app.keyboards import kb_actions, kb_back_home
from app.main import home_main
from app.pdf_report import build_pdf


class _DummyMessage:
    def __init__(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        self.chat = SimpleNamespace(id=999)
        self.edit_text = AsyncMock(side_effect=RuntimeError("cannot edit"))
        self.answer = AsyncMock()


class _DummyCallback:
    def __init__(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        self.from_user = SimpleNamespace(id=111, username="tester")
        self.message = _DummyMessage()
        self.answer = AsyncMock()
        self.data = "home:main"


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def test_back_home_helper_contains_both_buttons():
    markup = kb_back_home("calc:menu")
    data = [btn.callback_data for btn in _flatten(markup)]
    assert "calc:menu" in data
    assert "home:main" in data


def test_notify_status_keyboard_uses_nav_helper():
    markup = notify._status_keyboard(True)
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup)]
    assert "notify:off" in callbacks
    assert "notify:help" in callbacks
    assert "home:main" in callbacks


def test_premium_links_keyboard_has_back_home():
    markup = premium._kb_links([("Test", "https://example.com")])
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    assert "sub:menu" in callbacks
    assert "home:main" in callbacks


def test_subscription_menu_keyboard_has_navigation():
    markup = subscription._kb_sub_menu()
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    assert "sub:check" in callbacks
    assert "home:main" in callbacks


def test_referral_keyboard_has_navigation():
    markup = referral._kb_ref("https://example.com")
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    assert "home:main" in callbacks
    assert any(cb == "ref:menu" for cb in callbacks)


def test_card_actions_uses_discount_url_when_available(monkeypatch):
    monkeypatch.setattr(settings, "VELAVIE_URL", "https://velavie.example/offer")
    cards = [{"code": "T8_BLEND", "name": "Blend", "order_url": "https://shop/blend"}]
    markup = kb_actions(cards, back_cb="calc:menu")
    urls = [btn.url for btn in _flatten(markup) if btn.url]
    assert "https://velavie.example/offer" in urls


def test_picker_helper_appends_navigation_buttons():
    builder = InlineKeyboardBuilder()
    builder.button(text="Опция", callback_data="pick:test")
    picker._extend_with_back_home(builder, "pick:menu")
    markup = builder.as_markup()
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    assert "pick:menu" in callbacks
    assert "home:main" in callbacks


def test_build_pdf_returns_non_empty_bytes():
    pdf_bytes = build_pdf(
        title="Тестовый план",
        subtitle="Калькулятор MSD",
        actions=["Шаг 1", "Шаг 2"],
        products=["— T8 EXTRA: поддержка митохондрий"],
        notes="Фокус на регулярности сна и белке.",
        footer="Пояснения",
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000


def test_home_main_fallback_to_new_message():
    cb = _DummyCallback()
    asyncio.run(home_main(cb))
    cb.message.answer.assert_awaited()
    cb.answer.assert_awaited()
