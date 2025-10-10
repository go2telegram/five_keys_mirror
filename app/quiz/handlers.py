"""Router that exposes quiz launches via unified tests menu."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.exceptions import SkipHandler
from aiogram.types import CallbackQuery

from app.handlers import (
    quiz_energy as h_quiz_energy,
    quiz_gut as h_quiz_gut,
    quiz_immunity as h_quiz_immunity,
    quiz_sleep as h_quiz_sleep,
    quiz_stress as h_quiz_stress,
)

router = Router(name="quiz_tests")

_TestCallback = Callable[[CallbackQuery], Awaitable[None]]

_TEST_HANDLERS: dict[str, _TestCallback] = {
    "energy": h_quiz_energy.quiz_energy_start,
    "sleep": h_quiz_sleep.quiz_sleep_start,
    "stress": h_quiz_stress.quiz_stress_start,
    "immunity": h_quiz_immunity.quiz_immunity_start,
    "gut": h_quiz_gut.quiz_gut_start,
}


@router.callback_query(F.data.startswith("tests:"))
async def launch_quiz_from_tests_menu(callback: CallbackQuery) -> None:
    """Dispatch test callbacks to the existing quiz handlers."""

    data = callback.data or ""
    _, _, slug = data.partition(":")

    if slug == "menu":
        # Allow the navigator to handle rendering the tests menu.
        raise SkipHandler

    handler = _TEST_HANDLERS.get(slug)
    if handler is None:
        await callback.answer("Тест недоступен", show_alert=True)
        return

    await handler(callback)
