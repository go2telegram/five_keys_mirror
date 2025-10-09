"""Handlers that expose the catalog to end users."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.catalog.loader import load_catalog
from app.config import settings
from app.keyboards import kb_catalog_follow_up
from app.storage import touch_throttle
from app.utils import catalog_summary, safe_edit_text, send_product_cards

router = Router(name="catalog")
log = logging.getLogger("catalog")

CATALOG_COMMAND_THROTTLE = 3.0
CATALOG_CALLBACK_THROTTLE = 1.5


async def _send_catalog_menu(message: Message) -> None:
    catalog = load_catalog()
    lines = ["🛍 Каталог продуктов"]
    if settings.velavie_url:
        lines.append("Закажи со скидкой прямо в каталоге.")
    summary = catalog_summary()
    if summary:
        lines.extend(["", "Популярные позиции:"])
        lines.extend(f"• {item}" for item in summary)
    else:
        lines.append("Каталог загружается, попробуйте чуть позже.")

    markup = _build_catalog_markup(catalog)
    await message.answer("\n".join(lines), reply_markup=markup)


def _build_catalog_markup(catalog) -> "InlineKeyboardMarkup":
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    ordered = catalog.get("ordered") or list(catalog.get("products", {}))
    rows: list[int] = []
    for pid in ordered:
        product = catalog["products"].get(pid)
        if not product:
            continue
        title = product.get("title") or product.get("name") or pid
        builder.button(text=f"🛒 {title}", callback_data=f"catalog:view:{pid}")
        rows.append(1)
    if settings.velavie_url:
        builder.button(text="🔗 Заказать со скидкой", url=settings.velavie_url)
        rows.append(1)
    builder.button(text="⬅️ Назад", callback_data="home:main")
    builder.button(text="🏠 Домой", callback_data="home:main")
    rows.extend([2])
    builder.adjust(*rows)
    return builder.as_markup()


@router.message(Command("catalog"))
async def catalog_command(message: Message) -> None:
    if not message.from_user:
        return
    remaining = touch_throttle(message.from_user.id, "catalog:command", CATALOG_COMMAND_THROTTLE)
    if remaining > 0:
        await message.answer("Каталог уже открыт, попробуйте чуть позже.")
        log.debug("catalog_command throttled uid=%s remaining=%.2f", message.from_user.id, remaining)
        return
    await _send_catalog_menu(message)


@router.callback_query(F.data == "catalog:menu")
async def catalog_menu_callback(callback: CallbackQuery) -> None:
    if callback.from_user:
        remaining = touch_throttle(callback.from_user.id, "catalog:menu", CATALOG_CALLBACK_THROTTLE)
        if remaining > 0:
            await callback.answer("Каталог обновляется, попробуйте позже.", show_alert=False)
            log.debug(
                "catalog_menu throttled uid=%s remaining=%.2f",
                callback.from_user.id,
                remaining,
            )
            return
    await callback.answer()
    if callback.message:
        catalog = load_catalog()
        await safe_edit_text(
            callback.message,
            "🛍 Каталог продуктов\nВыбери продукт, чтобы узнать подробности:",
            _build_catalog_markup(catalog),
        )


@router.callback_query(F.data.startswith("catalog:view:"))
async def catalog_view_callback(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":", 2)
    product_id = parts[-1] if len(parts) == 3 else ""
    if not product_id:
        await callback.answer("Продукт не найден", show_alert=False)
        return

    if callback.from_user:
        remaining = touch_throttle(callback.from_user.id, f"catalog:view:{product_id}", CATALOG_CALLBACK_THROTTLE)
        if remaining > 0:
            await callback.answer("Слишком часто. Попробуйте чуть позже.", show_alert=False)
            log.debug(
                "catalog_view throttled uid=%s product=%s remaining=%.2f",
                callback.from_user.id,
                product_id,
                remaining,
            )
            return

    await send_product_cards(
        callback,
        title="Поддержка по твоей цели",
        products=[product_id],
        ctx=None,
        back_cb="catalog:menu",
        follow_up=("Что дальше?", kb_catalog_follow_up()),
    )


__all__ = ["router"]
