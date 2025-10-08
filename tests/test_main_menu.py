from app.keyboards import kb_main


def test_main_menu_contains_required_callbacks():
    markup = kb_main()
    callbacks = {btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data}
    expected = {
        "catalog:menu",
        "quiz:menu",
        "calc:menu",
        "pick:menu",
        "profile:open",
        "sub:menu",
        "help:open",
    }
    assert expected.issubset(callbacks)
