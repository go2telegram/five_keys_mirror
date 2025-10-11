"""Utilities for sending Premium upsell CTA messages."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.storage import SESSIONS

CTA_BUTTON_TEXT = "💎 Получить полный план (AI)"
_CTA_SEEN_KEY = "_premium_cta_shown"


def _mark_cta_shown(user_id: int | None) -> bool:
    if user_id is None:
        return False
    session = SESSIONS.setdefault(user_id, {})
    already = bool(session.get(_CTA_SEEN_KEY))
    if not already:
        session[_CTA_SEEN_KEY] = True
    return already


async def send_premium_cta(
    target: CallbackQuery | Message,
    text: str,
    *,
    source: str,
) -> None:
    """Send a Premium upsell prompt with a CTA button."""

    message = target.message if isinstance(target, CallbackQuery) else target
    if message is None:
        return

    user = target.from_user if isinstance(target, CallbackQuery) else target.from_user
    user_id = getattr(user, "id", None)
    if _mark_cta_shown(user_id):
        return

    if isinstance(target, CallbackQuery):
        await target.answer()

    builder = InlineKeyboardBuilder()
    builder.button(text=CTA_BUTTON_TEXT, callback_data=f"premium:cta:{source}")
    builder.button(text="🏠 Домой", callback_data="home:main")
    builder.adjust(2)
    markup = builder.as_markup()

    await message.answer(text, reply_markup=markup)


__all__ = ["CTA_BUTTON_TEXT", "send_premium_cta"]
