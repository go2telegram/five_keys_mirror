"""Telegram command for personalized recommendations."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.products import PRODUCTS, BUY_URLS
from recommendations.service import (
    get_reco,
    mark_recommendation_click,
    mark_recommendation_shown,
)

router = Router()


def _keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=item["title"], callback_data=f"recommend:open:{item['code']}")]
        for item in items
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _format_list(items: list[dict]) -> str:
    lines = ["Твои персональные рекомендации:"]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. <b>{item['title']}</b> — {item.get('description','')}")
    return "\n".join(lines)


@router.message(Command("recommend"))
async def recommend_cmd(message: Message) -> None:
    user_id = message.from_user.id
    items = await get_reco(user_id)
    if not items:
        await message.answer("Пока не могу подобрать — попробуй пройти квизы или калькуляторы.")
        return
    await message.answer(_format_list(items), reply_markup=_keyboard(items))
    await mark_recommendation_shown(user_id, [item["code"] for item in items])


@router.callback_query(F.data.startswith("recommend:open:"))
async def recommend_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    code = callback.data.split(":", 2)[2]
    product = PRODUCTS.get(code)
    if not product:
        await callback.message.answer("Упс, не нашла товар.")
        return
    await mark_recommendation_click(user_id, code)
    bullets = product.get("bullets", []) or []
    text_lines = [f"<b>{product.get('title', code)}</b>"]
    text_lines.extend(bullets)
    buy_url = BUY_URLS.get(code)
    if buy_url:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Купить", url=buy_url)]]
        )
    else:
        kb = None
    await callback.message.answer("\n".join(text_lines), reply_markup=kb)
