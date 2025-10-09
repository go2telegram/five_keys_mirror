"""Handlers for YAML-driven quizzes."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .engine import (
    QuizCallbackPayload,
    answer_callback,
    build_nav_callback_data,
    list_quizzes,
    load_quiz,
    navigation_callback,
    parse_callback_data,
    start_quiz,
)

router = Router()


@router.message(Command("tests"))
async def command_tests(message: Message) -> None:
    quizzes = list_quizzes()
    if not quizzes:
        await message.answer("Пока нет доступных тестов. Загляни позже!")
        return

    kb = InlineKeyboardBuilder()
    for quiz in quizzes:
        kb.button(
            text=quiz.title,
            callback_data=build_nav_callback_data(quiz.name, "next"),
        )
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


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_callbacks(call: CallbackQuery, state: FSMContext) -> None:
    payload: QuizCallbackPayload | None = parse_callback_data(call.data)
    if not payload:
        await call.answer("Кнопка не распознана", show_alert=True)
        return

    if payload.kind == "answer":
        await answer_callback(call, state, payload)
    else:
        await navigation_callback(call, state, payload)
