"""Repository helpers for user profile data."""

from __future__ import annotations

from typing import Any


async def get_user_profile(user_id: int) -> dict[str, Any] | None:
    """Return stored user profile data (empty fallback)."""

    return None


__all__ = ["get_user_profile"]
