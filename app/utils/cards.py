"""Helpers for rendering catalog-driven product cards."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from aiogram.types import CallbackQuery, Message
from aiogram.utils.media_group import MediaGroupBuilder

from app.catalog.loader import load_catalog, product_by_alias, product_by_id
from app.keyboards import kb_actions, kb_back_home

LOG = logging.getLogger(__name__)
MAX_TEXT = 3500
MAX_MEDIA = 3


def _resolve_catalog_product(code: str) -> dict | None:
    if not code:
        return None
    product = product_by_id(code)
    if product:
        return product
    return product_by_alias(code)


def _select_help(raw: object, ctx: str | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return None
    if ctx and ctx in raw:
        value = raw[ctx]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("severe", "moderate", "mild"):
                if key in value:
                    maybe = value[key]
                    if isinstance(maybe, str):
                        return maybe
            for item in value.values():
                if isinstance(item, str):
                    return item
            return None
    for maybe in raw.values():
        if isinstance(maybe, str):
            return maybe
        if isinstance(maybe, dict):
            for item in maybe.values():
                if isinstance(item, str):
                    return item
    return None


def _normalize_product(item: str | dict, ctx: str | None) -> dict | None:
    source: dict | None
    if isinstance(item, str):
        source = _resolve_catalog_product(item)
        if not source:
            return None
        source = dict(source)
    elif isinstance(item, dict):
        source = dict(item)
    else:
        return None

    order = source.get("order") or {}
    props = []
    for collection in (source.get("props"), source.get("benefits")):
        if isinstance(collection, list):
            props.extend(str(p) for p in collection if p)
    props = props[:5]

    helps_text = source.get("helps_text")
    if not helps_text:
        helps_text = _select_help(source.get("how_it_helps"), ctx)

    images: list[str] = []
    raw_images = source.get("images")
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, str) and img:
                images.append(img)
                if len(images) >= MAX_MEDIA:
                    break

    order_url = source.get("order_url") or order.get("velavie_link")
    if not order_url:
        order_url = order.get("url")

    name = source.get("title") or source.get("name") or source.get("code") or source.get("id") or "Product"

    return {
        "code": source.get("code") or source.get("id") or source.get("title") or name,
        "name": name,
        "short": source.get("short", ""),
        "props": props,
        "images": images,
        "order_url": order_url,
        "helps_text": helps_text,
    }


def prepare_cards(products: Iterable[str | dict], ctx: str | None = None) -> list[dict]:
    """Normalize product descriptors to a unified card structure."""

    return [card for card in (_normalize_product(item, ctx) for item in products) if card]


def render_product_text(product: dict, goal_ctx: str | None) -> tuple[str, list[str]]:
    """Return a header and bullet list for the given product."""

    header = f"<b>— {product.get('name', 'Product')}</b>"
    short = product.get("short")
    if short:
        header = f"{header}: {short}"

    bullets: list[str] = []
    for prop in (product.get("props") or [])[:5]:
        if prop:
            bullets.append(str(prop))

    helps = product.get("helps_text")
    if helps:
        bullets.append(f"<i>Как поможет сейчас:</i> {helps}")
    return header, bullets


def _collect_media(products: Sequence[dict]) -> list[str]:
    media: list[str] = []
    for product in products:
        for img in product.get("images", []) or []:
            if img and img not in media:
                media.append(img)
            if len(media) >= MAX_MEDIA:
                return media
    return media


async def send_product_cards(
    target: CallbackQuery | Message,
    title: str,
    products: Iterable[str | dict],
    *,
    ctx: str | None = None,
    headline: str | None = None,
    bullets: Sequence[str] | None = None,
    back_cb: str | None = None,
    with_actions: bool = True,
) -> None:
    """Render product cards for chat or callback targets."""

    cards = prepare_cards(products, ctx)

    message = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        await target.answer()

    if not cards:
        await message.answer(
            "Каталог временно недоступен. Попробуйте позже или свяжитесь с консультантом.",
            reply_markup=kb_back_home(back_cb=back_cb),
        )
        return

    media = MediaGroupBuilder(caption=None)
    for img in _collect_media(cards):
        media.add_photo(media=img)
    try:
        built = media.build()
    except Exception:  # pragma: no cover - defensive guard for aiogram internals
        built = []
    if built:
        try:
            await message.answer_media_group(built)
        except Exception:  # noqa: BLE001 - prefer to continue with text fallback
            LOG.exception("send_media_group failed")

    lines: list[str] = [f"<b>{title}</b>"]
    if headline:
        lines.extend(["", headline])
    if bullets:
        lines.extend(["", "Что можно сделать уже сегодня:"])
        lines.extend([f"• {item}" for item in bullets])
    lines.append("")
    lines.append("Поддержка:")
    lines.append("")

    for card in cards:
        header, card_bullets = render_product_text(card, ctx)
        lines.append(header)
        for item in card_bullets:
            lines.append(f"  · {item}")
        lines.append("")

    text = "\n".join(lines).strip()
    markup = kb_actions(cards, back_cb=back_cb) if with_actions else kb_back_home(back_cb)

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


def catalog_summary(goal: str | None = None) -> list[str]:
    """Return up to 6 product titles for a goal context."""

    data = load_catalog()
    ordered = data["ordered"]
    if goal:
        goal = goal.lower()
    result = []
    for pid in ordered:
        product = data["products"][pid]
        goals = product.get("goals") or []
        if not goal or goal in {str(g).lower() for g in goals}:
            result.append(product.get("title") or product.get("name") or pid)
        if len(result) >= 6:
            break
    return result


__all__ = ["catalog_summary", "prepare_cards", "render_product_text", "send_product_cards"]
