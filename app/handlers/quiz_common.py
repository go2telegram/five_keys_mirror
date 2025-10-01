"""Shared helpers for quiz result rendering."""

from __future__ import annotations

import logging
from typing import List

from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

from app.keyboards import kb_back_home

LOG = logging.getLogger(__name__)
MAX_TEXT = 3500
ERROR_TEXT = (
    "\u041f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u043e\u0448\u0438\u0431\u043a\u0430. "
    "\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437 \u043f\u043e\u0437\u0436\u0435."
)


def _action_kb(cards: List[dict]):
    kb = InlineKeyboardBuilder()
    for item in cards:
        url = item.get("order_url")
        name = item.get("name") or item.get("code")
        if url:
            kb.button(text=f"\u041a\u0443\u043f\u0438\u0442\u044c {name}", url=url)
    kb.button(text="PDF-\u043f\u043b\u0430\u043d", callback_data="report:last")
    kb.button(text="\u0417\u0430\u043a\u0430\u0437\u0430\u0442\u044c \u0441\u043e \u0441\u043a\u0438\u0434\u043a\u043e\u0439", callback_data="reg:open")
    kb.button(text="\u0414\u043e\u043c\u043e\u0439", callback_data="home:main")
    rows = [1] * len([b for b in kb.buttons if getattr(b, "url", None)]) + [1, 1, 1]
    kb.adjust(*rows)
    return kb.as_markup()


async def safe_edit(c: CallbackQuery, text: str, reply_markup):
    try:
        await c.message.edit_text(text, reply_markup=reply_markup)
    except Exception:  # noqa: BLE001 - we deliberately show fallback to the user
        LOG.exception("edit_text failed")
        await c.message.answer(ERROR_TEXT, reply_markup=kb_back_home(home_cb="home:main"))


async def send_product_cards(c: CallbackQuery, title: str, cards: List[dict]) -> None:
    if not cards:
        await c.message.answer(
            "\u041a\u0430\u0442\u0430\u043b\u043e\u0433 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d.",
            reply_markup=kb_back_home(home_cb="home:main"),
        )
        return

    media = MediaGroupBuilder(caption=None)
    for img in (cards[0].get("images") or [])[:3]:
        media.add_photo(media=img)
    built_media = media.build()
    if built_media:
        try:
            await c.message.answer_media_group(built_media)
        except Exception:  # noqa: BLE001
            LOG.exception("send_media_group failed")

    lines: List[str] = [
        f"<b>{title}</b>",
        "",
        "\u0427\u0442\u043e \u043c\u043e\u0436\u043d\u043e \u0441\u0434\u0435\u043b\u0430\u0442\u044c \u0443\u0436\u0435 \u0441\u0435\u0433\u043e\u0434\u043d\u044f:",
        "\u2022 \u0421\u043e\u043d \u0434\u043e 23:00, 7–9 \u0447",
        "\u2022 10 \u043c\u0438\u043d \u0443\u0442\u0440\u0435\u043d\u043d\u0435\u0433\u043e \u0441\u0432\u0435\u0442\u0430",
        "\u2022 30 \u043c\u0438\u043d \u0431\u044b\u0441\u0442\u0440\u043e\u0439 \u0445\u043e\u0434\u044c\u0431\u044b",
        "",
    ]
    for item in cards:
        name = item.get("name") or item.get("code")
        lines.append(f"<b>— {name}</b>: {item.get('short', '')}")
        for prop in (item.get("props") or [])[:5]:
            lines.append(f"  · {prop}")
        helps_text = item.get("helps_text")
        if helps_text:
            lines.append(f"<i>\u041a\u0430\u043a \u043f\u043e\u043c\u043e\u0436\u0435\u0442 \u0441\u0435\u0439\u0447\u0430\u0441:</i> {helps_text}")
        lines.append("")

    text = "\n".join(lines)
    markup = _action_kb(cards)
    if len(text) > MAX_TEXT:
        midpoint = len(lines) // 2
        await c.message.answer("\n".join(lines[:midpoint]))
        await c.message.answer("\n".join(lines[midpoint:]), reply_markup=markup)
        return

    await c.message.answer(text, reply_markup=markup)


__all__ = ["send_product_cards", "safe_edit"]
