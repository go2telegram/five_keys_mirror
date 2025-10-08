from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.keyboards import kb_back_home
from app.texts import REG_TEXT, REG_TEXT_UNAVAILABLE

router = Router()


@router.callback_query(F.data == "reg:open")
async def reg_open(c: CallbackQuery):
    url = settings.velavie_url
    await c.answer()
    if not url:
        await c.message.edit_text(REG_TEXT_UNAVAILABLE, reply_markup=kb_back_home())
        return

    await c.message.edit_text(REG_TEXT, reply_markup=build_reg_markup(url))


@router.message(Command("register"))
async def reg_command(message: Message) -> None:
    url = settings.velavie_url
    if not url:
        await message.answer(REG_TEXT_UNAVAILABLE, reply_markup=kb_back_home())
        return
    await message.answer(REG_TEXT, reply_markup=build_reg_markup(url))


def build_reg_markup(url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Перейти к регистрации", url=url)
    for row in kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb.as_markup()
