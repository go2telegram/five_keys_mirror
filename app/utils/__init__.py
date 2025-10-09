"""Utility helpers for rendering responses."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "build_order_link",
    "catalog_summary",
    "nav_footer",
    "prepare_cards",
    "render_product_text",
    "safe_edit_text",
    "send_product_cards",
]

_CARD_EXPORTS = {
    "build_order_link",
    "catalog_summary",
    "prepare_cards",
    "render_product_text",
    "send_product_cards",
}


def __getattr__(name: str) -> Any:  # pragma: no cover - simple delegation
    if name == "safe_edit_text":
        from .telegram import safe_edit_text  # local import to avoid circular dependency

        return safe_edit_text
    if name == "nav_footer":
        from .nav import nav_footer  # local import to avoid circular dependency

        return nav_footer
    if name in _CARD_EXPORTS:
        module = import_module("app.utils.cards")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:  # pragma: no cover - debugging helper
    return sorted(__all__)
