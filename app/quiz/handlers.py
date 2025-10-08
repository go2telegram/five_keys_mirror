"""Handlers for YAML-driven quizzes."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .engine import ANSWER_PREFIX, answer_callback, list_quizzes, load_quiz, start_quiz

router = Router()


@router.message(Command("tests"))
async def command_tests(message: Message) -> None:
    quizzes = list_quizzes()
    if not quizzes:
        await message.answer("Пока нет доступных тестов. Загляни позже!")
        return

    kb = InlineKeyboardBuilder()
    for quiz in quizzes:
        kb.button(text=quiz.title, callback_data=f"tests:{quiz.name}")
    kb.adjust(1)

    titles = "\n".join(f"• {quiz.title}" for quiz in quizzes)
    text = (
        "🧪 <b>Доступные тесты</b>\n\n"
        f"{titles}\n\nВыбирай тест, чтобы пройти его прямо сейчас."
    )
    await message.answer(text, reply_markup=kb.as_markup())


@router.message(Command("test"))
async def command_test(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not command.args:
        await message.answer("Укажи название теста, например: <code>/test energy</code>.")
        return

    name = command.args.strip().split()[0].lower()
    try:
        load_quiz(name)
    except FileNotFoundError:
        await message.answer("Тест не найден. Попробуй /tests чтобы увидеть список.")
        return

    await start_quiz(message, state, name)


@router.callback_query(F.data.startswith("tests:"))
async def quiz_callback(call: CallbackQuery, state: FSMContext) -> None:
    data = call.data or ""
    if data.startswith(f"{ANSWER_PREFIX}:"):
        return

    _, _, name = data.partition(":")
    name = name.strip().lower()
    if not name:
        await call.answer()
        return

    try:
        load_quiz(name)
    except FileNotFoundError:
        await call.answer("Тест недоступен", show_alert=True)
        return

    await start_quiz(call, state, name)


@router.callback_query(F.data.startswith(f"{ANSWER_PREFIX}:"))
async def quiz_answer(call: CallbackQuery, state: FSMContext) -> None:
    await answer_callback(call, state)
