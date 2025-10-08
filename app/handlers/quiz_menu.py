# app/handlers/quiz_menu.py
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards import kb_quiz_menu
from app.utils import safe_edit_text

router = Router()


@router.callback_query(F.data == "quiz:menu")
async def quiz_menu(c: CallbackQuery):
    await c.answer()
    await safe_edit_text(
        c.message,
        "🗂 <b>Все квизы</b>\n\nВыбери ключ здоровья, который хочешь проверить:",
        kb_quiz_menu(),
    )
