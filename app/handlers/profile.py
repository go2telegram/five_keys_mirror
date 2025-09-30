from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards import kb_back_home

router = Router()

_PROFILE_PLACEHOLDER = "👤 Профиль: скоро здесь будет функционал."


@router.callback_query(F.data == "profile:open")
async def profile_open(c: CallbackQuery) -> None:
    await c.message.edit_text(
        _PROFILE_PLACEHOLDER,
        reply_markup=kb_back_home("home"),
    )
