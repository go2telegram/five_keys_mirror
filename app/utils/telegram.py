from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


def _markups_equal(first: Any, second: Any) -> bool:
    if first is second:
        return True
    if first is None or second is None:
        return first is None and second is None
    try:
        return first.model_dump() == second.model_dump()
    except AttributeError:
        return first == second


async def safe_edit_text(
    message: Message | None,
    new_text: str,
    new_markup: Any | None = None,
) -> None:
    if message is None:
        return
    if message.text == new_text and _markups_equal(message.reply_markup, new_markup):
        return
    try:
        await message.edit_text(new_text, reply_markup=new_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise
