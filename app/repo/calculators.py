"""Helpers for retrieving calculator history."""

from __future__ import annotations

from typing import Any, List


async def get_user_calcs(user_id: int) -> List[dict[str, Any]]:
    """Return stored calculator payloads for the given user."""

    return []


__all__ = ["get_user_calcs"]
