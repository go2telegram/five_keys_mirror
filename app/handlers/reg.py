from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards import kb_back_home
from app.texts import REG_TEXT, REG_TEXT_UNAVAILABLE
from app.utils import safe_edit_text
from app.link_manager import get_register_link

router = Router()


@router.callback_query(F.data == "reg:open")
async def reg_open(c: CallbackQuery):
    url = await get_register_link()
    await c.answer()
    if not url:
        await safe_edit_text(c.message, REG_TEXT_UNAVAILABLE, kb_back_home())
        return

    await safe_edit_text(c.message, REG_TEXT, build_reg_markup(url))


def build_reg_markup(url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Перейти к регистрации", url=url)
    for row in kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb.as_markup()
