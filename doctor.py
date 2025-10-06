"""Service health checks for the bot runtime."""

import asyncio
import os
from typing import Final

import httpx

from app.config import settings


DEFAULT_TIMEOUT: Final[float] = 5.0


async def check_metrics_endpoint() -> None:
    metrics_url = os.getenv(
        "METRICS_URL",
        f"http://{settings.WEB_HOST}:{settings.WEB_PORT}/metrics",
    )

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.get(metrics_url)

    if response.status_code != 200:
        raise SystemExit(
            f"/metrics health-check failed: HTTP {response.status_code}"  # noqa: TRY003
        )

    payload = response.text
    if "bot_updates_total" not in payload or "bot_update_latency_seconds" not in payload:
        raise SystemExit("/metrics missing required counters")


async def main() -> None:
    await check_metrics_endpoint()


if __name__ == "__main__":
    asyncio.run(main())
