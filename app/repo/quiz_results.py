"""Repository helpers for quiz results."""

from __future__ import annotations

from typing import Any


async def get_user_quiz_results(user_id: int) -> list[dict[str, Any]]:
    """Return stored quiz results for the user (empty fallback)."""

    return []


__all__ = ["get_user_quiz_results"]
