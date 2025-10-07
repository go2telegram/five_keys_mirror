"""Legacy helpers that expose prepared card metadata."""

from __future__ import annotations

from typing import Iterable

from .loader import load_catalog, product_by_alias, product_by_id


def _resolve_product(code: str) -> dict | None:
    product = product_by_id(code)
    if product:
        return product
    return product_by_alias(code)


def load_catalog_map() -> dict:
    data = load_catalog()
    return data["products"].copy()


def product_meta(code: str) -> dict | None:
    product = _resolve_product(code)
    if not product:
        return None

    order = product.get("order") or {}
    helps = product.get("how_it_helps") or {}
    images = product.get("images") or []
    benefits = product.get("benefits") or []

    return {
        "code": product.get("id", code),
        "name": product.get("title") or product.get("name") or code,
        "short": product.get("short", ""),
        "props": [str(item) for item in benefits[:5]],
        "images": [str(img) for img in images[:5]],
        "order_url": order.get("velavie_link"),
        "helps": helps,
    }


def _select_help(raw: dict | str | None, context: str, level: str | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw

    ctx_value = raw.get(context)
    if ctx_value is None:
        return None
    if isinstance(ctx_value, str):
        return ctx_value

    if level and level in ctx_value:
        return ctx_value[level]

    for fallback in ("moderate", "mild", "severe"):
        if fallback in ctx_value:
            return ctx_value[fallback]
    for value in ctx_value.values():
        return value
    return None


def pick_for_context(context: str, level: str | None, codes: Iterable[str]) -> list[dict]:
    cards: list[dict] = []
    for code in codes:
        meta = product_meta(code)
        if not meta:
            continue
        helps_text = _select_help(meta.get("helps"), context, level)
        cards.append(
            {
                "code": meta["code"],
                "name": meta.get("name", meta["code"]),
                "short": meta.get("short", ""),
                "props": list(meta.get("props", []) or []),
                "images": list(meta.get("images", []) or []),
                "order_url": meta.get("order_url"),
                "helps_text": helps_text,
            }
        )
    return cards


__all__ = ["load_catalog_map", "pick_for_context", "product_meta"]
