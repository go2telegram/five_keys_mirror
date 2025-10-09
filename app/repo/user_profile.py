"""Access helpers for user profile snapshots."""

from __future__ import annotations

from typing import Any, Dict


async def get_user_profile(user_id: int) -> Dict[str, Any] | None:
    """Return a lightweight profile dictionary for the user if available."""

    return None


__all__ = ["get_user_profile"]
