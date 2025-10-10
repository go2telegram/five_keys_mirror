"""Fallback handler for messages that were not processed by other routers."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards import kb_back_home
from app.utils import reply_or_edit

logger = logging.getLogger("message.fallback")

router = Router(name="message_fallback")


@router.message()
async def on_unhandled_message(message: Message, state: FSMContext | None = None) -> None:
    user_id = getattr(message.from_user, "id", None)
    state_name = None
    if state is not None:
        with suppress(Exception):
            state_name = await state.get_state()
        with suppress(Exception):
            await state.clear()

    logger.warning(
        "Unhandled message text=%r uid=%s state=%s",
        message.text,
        user_id,
        state_name,
    )

    await reply_or_edit(
        message,
        "Я не распознал сообщение. Нажмите «Домой» или выберите действие ниже.",
        reply_markup=kb_back_home(),
    )
