"""Handlers for catalog interactions (buy buttons, etc.)."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog import get_buy_url, get_product_info, record_click
from app.catalog.analytics import normalize_campaign
from app.storage import USERS
from app.utils.utm import add_utm_params

router = Router()


@router.callback_query(F.data.regexp(r"^catalog:buy:[^:]+:[^:]+$"))
async def catalog_buy_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return
    _, _, product_id, campaign = callback.data.split(":", 3)
    campaign = normalize_campaign(campaign)
    product = get_product_info(product_id)
    url = get_buy_url(product_id)
    if not url:
        await callback.answer("Ссылка недоступна", show_alert=True)
        return

    utm_url = add_utm_params(
        url,
        {
            "utm_source": "tg_bot",
            "utm_medium": "catalog",
            "utm_campaign": campaign,
            "utm_content": product_id,
        },
    )

    title = product.get("title", product_id) if product else product_id
    safe_title = html.escape(title)
    source = USERS.get(callback.from_user.id, {}).get("source")
    record_click(callback.from_user.id, source, product_id, campaign)

    await callback.answer("Ссылка отправлена")
    await callback.message.answer(
        f"🛒 <b>{safe_title}</b>\n"
        f"<a href=\"{html.escape(utm_url)}\">Перейти к покупке</a>",
        disable_web_page_preview=True,
    )


__all__ = ["router"]
