"""Catalog helper smoke tests."""

from app.catalog.api import pick_for_context
from app.keyboards import kb_actions


def test_pick_for_context_uses_level_specific_text():
    cards = pick_for_context("energy", "moderate", ["T8_BLEND", "VITEN"])
    assert cards
    assert all("name" in card for card in cards)


def test_pick_for_context_fallback_when_level_missing():
    cards = pick_for_context("energy", None, ["T8_EXTRA"])
    assert cards


def test_card_actions_keyboard_contains_core_buttons():
    cards = [
        {
            "code": "T8_BLEND",
            "name": "T8 BLEND",
            "order_url": "https://example.com/blend",
        }
    ]
    markup = kb_actions(cards, back_cb="calc:menu")
    flat = [btn for row in markup.inline_keyboard for btn in row]
    assert any(btn.url for btn in flat if "Купить" in btn.text)
    assert any(getattr(btn, "callback_data", None) == "cart:add:T8_BLEND" for btn in flat)
    assert any(getattr(btn, "callback_data", None) == "report:last" for btn in flat)
    discount_buttons = [btn for btn in flat if "Заказать" in btn.text]
    assert discount_buttons
    assert any(
        btn.url or getattr(btn, "callback_data", None) == "reg:open" for btn in discount_buttons
    )
    assert any(btn.text == "📝 Консультация" for btn in flat)
    assert any(getattr(btn, "callback_data", None) == "calc:menu" for btn in flat)
    assert any(getattr(btn, "callback_data", None) == "home:main" for btn in flat)
