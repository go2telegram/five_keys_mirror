"""Inline help menu handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards import kb_back_home

router = Router()

HELP_TEXT = (
    "❓ <b>Помощь</b>\n\n"
    "• Раздел «Каталог» — карточки всех 38 продуктов.\n"
    "• В «Тестах» и «Калькуляторах» можно собрать теги для рекомендаций.\n"
    "• В профиле — обновление анкеты и персональные подборки.\n\n"
    "Если появился вопрос — ответь на это сообщение или напиши куратору, и команда свяжется с тобой."
)


@router.callback_query(F.data == "help:menu")
async def help_menu(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text(HELP_TEXT, reply_markup=kb_back_home("home:main"))
