"""Shared helpers for quiz and calculator result rendering."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from aiogram.types import CallbackQuery, Message
from aiogram.utils.media_group import MediaGroupBuilder

from app.keyboards import kb_back_home, kb_card_actions

LOG = logging.getLogger(__name__)
MAX_TEXT = 3500
ERROR_TEXT = (
    "\u041f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u043e\u0448\u0438\u0431\u043a\u0430. "
    "\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437 "
    "\u043f\u043e\u0437\u0436\u0435."
)


async def safe_edit(c: CallbackQuery, text: str, reply_markup) -> None:
    try:
        await c.message.edit_text(text, reply_markup=reply_markup)
    except Exception:  # noqa: BLE001 - deliberate fall back to a safe message
        LOG.exception("edit_text failed")
        await c.message.answer(ERROR_TEXT, reply_markup=kb_back_home())


def _collect_images(cards: Iterable[dict]) -> list[str]:
    images: list[str] = []
    for card in cards:
        for img in card.get("images") or []:
            images.append(img)
            if len(images) >= 3:
                return images
    return images


def _build_lines(
    title: str,
    cards: Iterable[dict],
    headline: str | None,
    bullets: Sequence[str] | None,
) -> list[str]:
    lines: list[str] = [f"<b>{title}</b>"]
    if headline:
        lines.extend(["", headline])

    if bullets:
        lines.extend(["", "Что можно сделать уже сегодня:"])
        lines.extend([f"• {item}" for item in bullets])

    lines.append("")
    lines.append("Поддержка:")

    for item in cards:
        name = item.get("name") or item.get("code") or "Product"
        lines.append(f"<b>— {name}</b>: {item.get('short', '')}")
        for prop in (item.get("props") or [])[:5]:
            lines.append(f"  · {prop}")
        helps_text = item.get("helps_text")
        if helps_text:
            lines.append("<i>Как поможет сейчас:</i> {0}".format(helps_text))
        lines.append("")

    return lines


async def send_product_cards(
    target: CallbackQuery | Message,
    title: str,
    cards: list[dict],
    *,
    headline: str | None = None,
    bullets: Sequence[str] | None = None,
    back_cb: str | None = None,
) -> None:
    if not cards:
        unavailable_text = "Каталог временно недоступен. " "Попробуйте позже или свяжитесь с консультантом."
        message = target.message if isinstance(target, CallbackQuery) else target
        await message.answer(unavailable_text, reply_markup=kb_back_home(back_cb=back_cb))
        if isinstance(target, CallbackQuery):
            await target.answer()
        return

    message = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        await target.answer()

    media = MediaGroupBuilder(caption=None)
    for img in _collect_images(cards):
        media.add_photo(media=img)
    built_media = media.build()
    if built_media:
        try:
            await message.answer_media_group(built_media)
        except Exception:  # noqa: BLE001 - swallow and continue with text fallback
            LOG.exception("send_media_group failed")

    lines = _build_lines(title, cards, headline, bullets)
    text = "\n".join(lines).strip()
    markup = kb_card_actions(cards, back_cb=back_cb)

    if len(text) > MAX_TEXT:
        midpoint = len(lines) // 2
        first = "\n".join(lines[:midpoint]).strip()
        second = "\n".join(lines[midpoint:]).strip()
        if first:
            await message.answer(first)
        if second:
            await message.answer(second, reply_markup=markup)
        return

    await message.answer(text, reply_markup=markup)


__all__ = ["send_product_cards", "safe_edit"]
