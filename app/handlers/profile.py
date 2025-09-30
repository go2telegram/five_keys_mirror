from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.keyboards import kb_back_home

router = Router()

_PROFILE_PLACEHOLDER = (
    "\u0420\u0430\u0437\u0434\u0435\u043b \u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435. "
    "\u0421\u043a\u043e\u0440\u043e \u0437\u0434\u0435\u0441\u044c \u0431\u0443\u0434\u0435\u0442 \u0444\u0443\u043d\u043a\u0446\u0438\u043e\u043d\u0430\u043b."
)


@router.callback_query(F.data == "profile:open")
async def profile_open(c: CallbackQuery) -> None:
    await c.message.edit_text(
        _PROFILE_PLACEHOLDER,
        reply_markup=kb_back_home(),
    )
