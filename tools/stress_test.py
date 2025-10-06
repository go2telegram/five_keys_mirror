#!/usr/bin/env python3
"""Minimal helper to generate HTTP load for manual autoscaling tests."""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

import httpx

LOGGER = logging.getLogger("stress_test")


async def worker(client: httpx.AsyncClient, url: str, delay: float, stop_at: float, identifier: int) -> None:
    sent = 0
    errors = 0
    while time.monotonic() < stop_at:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            errors += 1
            LOGGER.warning("worker %s request failed: %s", identifier, exc)
        else:
            sent += 1
        if delay:
            await asyncio.sleep(delay)
    LOGGER.info("worker %s finished: sent=%s errors=%s", identifier, sent, errors)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Send a burst of HTTP requests.")
    parser.add_argument("--url", default="http://localhost:8000/", help="Target URL to hit.")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers.")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay between requests per worker (seconds).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    timeout = httpx.Timeout(5.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        stop_at = time.monotonic() + args.duration
        tasks = [
            asyncio.create_task(worker(client, args.url, args.delay, stop_at, worker_id))
            for worker_id in range(args.workers)
        ]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
