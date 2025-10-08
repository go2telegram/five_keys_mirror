from __future__ import annotations

from app.keyboards import kb_calc_menu, kb_main, kb_quiz_menu


def _callbacks(markup) -> list[str | None]:
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


def test_main_menu_shows_primary_sections() -> None:
    callbacks = _callbacks(kb_main())
    assert callbacks == [
        "catalog:menu",
        "quiz:menu",
        "calc:menu",
        "pick:menu",
        "profile:open",
        "sub:menu",
        "help:menu",
    ]


def test_quiz_menu_has_five_tests() -> None:
    callbacks = _callbacks(kb_quiz_menu())
    assert callbacks.count("quiz:energy") == 1
    assert callbacks.count("quiz:deficits") == 0
    assert callbacks == [
        "quiz:energy",
        "quiz:immunity",
        "quiz:gut",
        "quiz:sleep",
        "quiz:stress",
        "home:main",
    ]


def test_calc_menu_lists_four_calculators() -> None:
    callbacks = _callbacks(kb_calc_menu())
    assert callbacks[:4] == ["calc:water", "calc:kcal", "calc:bmi", "calc:macros"]
    assert callbacks[-2:] == ["home:main", "home:main"]
    assert "calc:msd" not in callbacks
