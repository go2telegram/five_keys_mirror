"""Product catalog access helpers for quiz results."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Iterable

CAT_PATH = os.path.join(os.path.dirname(__file__), "products.json")


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """Load the product catalog from disk once."""
    with open(CAT_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


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
    """Return prepared product cards for the given quiz context."""
    catalog = load_catalog()
    cards: list[dict] = []
    for code in codes:
        data = catalog.get(code)
        if not data:
            continue
        helps_text = _select_help(data.get("helps"), context, level)
        cards.append(
            {
                "code": code,
                "name": data.get("name", code),
                "short": data.get("short", ""),
                "props": list(data.get("props", []) or []),
                "images": list(data.get("images", []) or []),
                "order_url": data.get("order_url"),
                "helps_text": helps_text,
            }
        )
    return cards


__all__ = ["load_catalog", "pick_for_context"]
