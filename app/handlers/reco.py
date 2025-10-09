"""Handlers for recommendation interactions (buy clicks etc.)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.repo import events as events_repo, users as users_repo
from app.storage import commit_safely
from app.utils.cards import prepare_cards

LOG = logging.getLogger(__name__)

router = Router(name="reco")


def _resolve_product_payload(code: str) -> dict[str, Any] | None:
    cards = prepare_cards([code])
    if not cards:
        return None
    card = cards[0]
    order_url = card.get("order_url") or settings.velavie_url
    if not order_url:
        return None
    return {
        "code": str(card.get("code") or code),
        "name": str(card.get("name") or code),
        "order_url": str(order_url),
    }


@router.callback_query(F.data.startswith("reco:buy:"))
async def handle_reco_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None:
        return

    _, _, raw_code = callback.data.partition(":buy:")
    code = raw_code.strip()
    if not code:
        return

    payload = _resolve_product_payload(code)
    if payload is None:
        LOG.warning("reco: unknown product code for buy click: %s", code)
        await callback.message.answer("Ссылка на заказ временно недоступна, попробуйте позже.")
        return

    user_id = callback.from_user.id
    username = callback.from_user.username

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, username)
        await events_repo.log(
            session,
            user_id,
            "reco_click_buy",
            {"product": payload["code"], "order_url": payload["order_url"]},
        )
        await commit_safely(session)

    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть магазин", url=payload["order_url"])
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.adjust(1, 1)

    message = callback.message
    if message is not None:
        await message.answer(
            f"🛒 <b>{payload['name']}</b> — переход к оформлению заказа:",
            reply_markup=kb.as_markup(),
        )
