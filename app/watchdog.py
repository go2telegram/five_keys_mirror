from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx


logger = logging.getLogger(__name__)

RestartCallback = Callable[[str], Awaitable[None]]


async def watchdog_loop(
    ping_url: str,
    trigger_restart: RestartCallback,
    *,
    interval: float = 5.0,
    timeout: float = 3.0,
    failure_threshold: int = 3,
) -> None:
    """Continuously poll the health endpoint and trigger recovery if needed."""

    failures = 0
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                response = await client.get(ping_url)
                if response.status_code == 200:
                    failures = 0
                else:
                    failures += 1
                    logger.warning(
                        "Watchdog ping returned HTTP %s from %s", response.status_code, ping_url
                    )
            except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
                raise
            except Exception as exc:  # noqa: BLE001 - we want to recover on any failure
                failures += 1
                logger.warning("Watchdog ping failed (%s/%s): %s", failures, failure_threshold, exc)

            if failures >= failure_threshold:
                logger.error("Watchdog triggering restart after %s consecutive failures", failures)
                await trigger_restart("watchdog-ping")
                failures = 0

            await asyncio.sleep(interval)


def start_watchdog(
    ping_url: str,
    trigger_restart: RestartCallback,
    *,
    interval: float = 5.0,
    timeout: float = 3.0,
    failure_threshold: int = 3,
) -> asyncio.Task[None]:
    loop = asyncio.get_running_loop()
    return loop.create_task(
        watchdog_loop(
            ping_url,
            trigger_restart,
            interval=interval,
            timeout=timeout,
            failure_threshold=failure_threshold,
        )
    )
