from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import REG_TEXT
from app.config import settings

router = Router()

@router.callback_query(F.data == "reg:open")
async def reg_open(c: CallbackQuery):
    kb = InlineKeyboardBuilder()
    if settings.VILAVI_REF_LINK_DISCOUNT:
        kb.button(text="🎁 Перейти к регистрации", url=settings.VILAVI_REF_LINK_DISCOUNT)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1)
    await c.message.edit_text(REG_TEXT, reply_markup=kb.as_markup())

