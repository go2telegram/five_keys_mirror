"""Fallback handler for unmatched callback queries."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


logger = logging.getLogger("callback.fallback")

router = Router(name="callback_fallback")


@router.callback_query()
async def callback_catch_all(call: CallbackQuery, state: FSMContext | None = None) -> None:
    state_value = None
    if state is not None:
        with suppress(Exception):
            state_value = await state.get_state()

    logger.warning(
        "Unhandled callback data=%r user_id=%s message_id=%s state=%s",
        call.data,
        getattr(call.from_user, "id", None),
        getattr(call.message, "message_id", None),
        state_value,
    )

    with suppress(Exception):
        await call.answer("Обнови сообщение или нажми Домой", show_alert=True)
