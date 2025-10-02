# app/handlers/quiz_menu.py
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards import kb_quiz_menu

router = Router()


@router.callback_query(F.data == "quiz:menu")
async def quiz_menu(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text(
        "🗂 <b>Все квизы</b>\n\nВыбери ключ здоровья, который хочешь проверить:", reply_markup=kb_quiz_menu()
    )
