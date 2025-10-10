"""Handlers for YAML-driven quizzes."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n import resolve_locale
from app.texts import Texts

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
    texts = Texts(resolve_locale(getattr(message.from_user, "language_code", None)))
    if not quizzes:
        await message.answer(texts.quiz.no_quizzes())
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
    texts = Texts(resolve_locale(getattr(message.from_user, "language_code", None)))
    if not command.args:
        await message.answer(texts.quiz.enter_name())
        return

    name = command.args.strip().split()[0].lower()
    try:
        load_quiz(name)
    except FileNotFoundError:
        await message.answer(texts.quiz.not_found())
        return

    await start_quiz(message, state, name)


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_callbacks(call: CallbackQuery, state: FSMContext) -> None:
    payload: QuizCallbackPayload | None = parse_callback_data(call.data)
    texts = Texts(resolve_locale(getattr(call.from_user, "language_code", None)))
    if not payload:
        await call.answer(texts.quiz.button_unrecognized(), show_alert=True)
        return

    if payload.kind == "answer":
        await answer_callback(call, state, payload)
    else:
        await navigation_callback(call, state, payload)
