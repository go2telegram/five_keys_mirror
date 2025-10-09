"""Utilities for sending Premium upsell CTA messages."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

CTA_BUTTON_TEXT = "💎 Получить полный план (AI)"


async def send_premium_cta(
    target: CallbackQuery | Message,
    text: str,
    *,
    source: str,
) -> None:
    """Send a Premium upsell prompt with a CTA button."""

    message = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        await target.answer()

    builder = InlineKeyboardBuilder()
    builder.button(text=CTA_BUTTON_TEXT, callback_data=f"premium:cta:{source}")
    markup = builder.as_markup()

    await message.answer(text, reply_markup=markup)


__all__ = ["CTA_BUTTON_TEXT", "send_premium_cta"]
