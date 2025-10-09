"""Repository helpers for calculator results."""

from __future__ import annotations

from typing import Any


async def get_user_calcs(user_id: int) -> list[dict[str, Any]]:
    """Return stored calculator outputs for the user (empty fallback)."""

    return []


__all__ = ["get_user_calcs"]
