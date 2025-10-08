"""Shared helpers for quiz and calculator result rendering."""

from __future__ import annotations

import logging

from aiogram.types import CallbackQuery

from app.keyboards import kb_back_home
from app.utils import safe_edit_text
from app.utils.cards import send_product_cards

LOG = logging.getLogger(__name__)
ERROR_TEXT = (
    "\u041f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u043e\u0448\u0438\u0431\u043a\u0430. "
    "\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437 "
    "\u043f\u043e\u0437\u0436\u0435."
)


async def safe_edit(c: CallbackQuery, text: str, reply_markup) -> None:
    if c.message is None:
        LOG.warning("safe_edit called without message")
        return
    try:
        await safe_edit_text(c.message, text, reply_markup)
    except Exception:  # noqa: BLE001 - deliberate fall back to a safe message
        LOG.exception("edit_text failed")
        await c.message.answer(ERROR_TEXT, reply_markup=kb_back_home())


__all__ = ["safe_edit", "send_product_cards"]
