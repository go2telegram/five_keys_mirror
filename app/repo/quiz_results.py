"""Lightweight accessors for cached quiz results."""

from __future__ import annotations

from typing import Any, List


async def get_user_quiz_results(user_id: int) -> List[dict[str, Any]]:
    """Return stored quiz results for a user, if available."""

    return []


__all__ = ["get_user_quiz_results"]
