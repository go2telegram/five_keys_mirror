"""Handlers for opening the quiz/tests menu."""

from contextlib import suppress

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.keyboards import kb_tests_menu

router = Router()

MENU_TEXT = (
    "🧠 <b>Тесты</b>\n\n"
    "Выбери направление, чтобы пройти экспресс-опрос и получить рекомендации."
)


@router.callback_query(F.data.in_({"quiz:menu", "tests:menu"}))
async def quiz_menu(c: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await c.answer()
    if not c.message:
        return
    with suppress(Exception):
        await c.message.edit_text(MENU_TEXT, reply_markup=kb_tests_menu())
        return
    await c.message.answer(MENU_TEXT, reply_markup=kb_tests_menu())
