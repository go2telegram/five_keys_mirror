from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BASE_BUTTONS: tuple[tuple[str, str], ...] = (
    ("🏠 Главное меню", "home:main"),
    ("🧪 К тестам", "menu:tests"),
    ("🎯 Подбор продукта", "pick:menu"),
    ("🛍 Каталог", "catalog:menu"),
)


def _normalize_extra(extra: InlineKeyboardButton | tuple[str, str] | tuple[str, str, bool]) -> InlineKeyboardButton:
    if isinstance(extra, InlineKeyboardButton):
        return extra
    if not isinstance(extra, tuple) or len(extra) < 2:
        raise ValueError("nav_footer extras must be InlineKeyboardButton or (text, value)")

    text, payload, *rest = extra
    if not isinstance(text, str):
        raise ValueError("nav_footer extra text must be a string")
    if not isinstance(payload, str):
        raise ValueError("nav_footer extra payload must be a string")

    is_url = bool(rest[0]) if rest else payload.startswith("http")
    if is_url:
        return InlineKeyboardButton(text=text, url=payload)
    return InlineKeyboardButton(text=text, callback_data=payload)


def nav_footer(*extras: InlineKeyboardButton | tuple[str, str] | tuple[str, str, bool]) -> InlineKeyboardMarkup:
    """Build a unified navigation footer with optional extra buttons."""

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text=BASE_BUTTONS[0][0], callback_data=BASE_BUTTONS[0][1]),
        InlineKeyboardButton(text=BASE_BUTTONS[1][0], callback_data=BASE_BUTTONS[1][1]),
    )
    builder.row(
        InlineKeyboardButton(text=BASE_BUTTONS[2][0], callback_data=BASE_BUTTONS[2][1]),
        InlineKeyboardButton(text=BASE_BUTTONS[3][0], callback_data=BASE_BUTTONS[3][1]),
    )

    if extras:
        for extra in extras:
            button = _normalize_extra(extra)
            builder.row(button)

    return builder.as_markup()


__all__ = ["nav_footer"]
