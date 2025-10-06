"""Async job to run global knowledge synchronisation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from knowledge.sync import get_service, is_enabled

logger = logging.getLogger(__name__)


async def sync_global_knowledge() -> list[dict[str, Any]]:
    """Run a single synchronisation cycle if the feature is enabled."""
    if not is_enabled():
        logger.debug("Global knowledge sync disabled; skipping job")
        return []

    service = get_service()
    result = await service.sync_with_peers()
    logger.info("Knowledge sync completed: %s", result)
    return result


if __name__ == "__main__":
    asyncio.run(sync_global_knowledge())
