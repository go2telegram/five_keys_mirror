from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.types import CallbackQuery, Message

_SAFE_EDIT_LOG = logging.getLogger("telegram.safe_edit")


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
) -> Message | None:
    if message is None:
        return None
    if message.text == new_text and _markups_equal(message.reply_markup, new_markup):
        return message
    try:
        return await message.edit_text(new_text, reply_markup=new_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return message
        _SAFE_EDIT_LOG.debug("edit_text failed; falling back to answer", exc_info=True)
        return await _answer_fallback(message, new_text, new_markup)
    except (TelegramForbiddenError, TelegramNotFound):
        _SAFE_EDIT_LOG.debug(
            "edit_text failed with forbidden/not found; falling back", exc_info=True
        )
        return await _answer_fallback(message, new_text, new_markup)


async def reply_or_edit(
    target: CallbackQuery | Message,
    text: str,
    reply_markup: Any | None = None,
) -> Message | None:
    if isinstance(target, Message):
        return await target.answer(text, reply_markup=reply_markup)

    message = target.message
    if message is not None:
        try:
            result = await safe_edit_text(message, text, reply_markup)
            if result is not None:
                return result
        except Exception:
            _SAFE_EDIT_LOG.debug(
                "reply_or_edit: safe_edit_text failed, replying instead", exc_info=True
            )
            return await message.answer(text, reply_markup=reply_markup)
        return await message.answer(text, reply_markup=reply_markup)

    await target.answer(text, show_alert=True)
    return None


async def _answer_fallback(message: Message, text: str, reply_markup: Any | None) -> Message | None:
    try:
        return await message.answer(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return message
        _SAFE_EDIT_LOG.warning("fallback answer failed", exc_info=True)
        raise
    except Exception:
        _SAFE_EDIT_LOG.warning("fallback answer failed", exc_info=True)
        raise
