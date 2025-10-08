from app.faq import get_faq_item, load_faq
from app.handlers import help as help_handlers


def _flatten_callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]


def test_load_faq_returns_items():
    items = load_faq()
    assert items
    sample = items[0]
    fetched = get_faq_item(sample["id"])
    assert fetched == sample


def test_help_keyboard_lists_all_questions():
    markup = help_handlers._build_faq_keyboard().as_markup()
    callbacks = _flatten_callbacks(markup)
    for item in load_faq():
        assert f"help:item:{item['id']}" in callbacks
    assert "lead:start" in callbacks
    assert "home:main" in callbacks
