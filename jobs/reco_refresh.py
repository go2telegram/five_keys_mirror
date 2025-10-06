"""Nightly job to refresh recommendation vectors."""
from __future__ import annotations

from recommendations.service import (
    active_user_ids,
    rebuild_item_matrix,
    refresh_user_cache,
)


async def refresh_recommendations() -> None:
    matrix = await rebuild_item_matrix()
    for user_id in active_user_ids():
        await refresh_user_cache(user_id, matrix=matrix)
