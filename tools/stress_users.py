"""Simple concurrent stress-test runner for the Five Keys bot.

The script simulates hundreds of concurrent users that sequentially
exercise the most frequently used admin flows: catalog browsing, quiz
navigation and recommendation retrieval.  It is intentionally lightweight
so it can be executed from a developer workstation against a staging
environment while still delivering actionable latency percentiles.

Example:

    python tools/stress_users.py --base-url http://localhost:5000 \
        --users 750 --rate 200

The script prints a short textual report with latency percentiles and
error counts.  It can also persist the raw metrics into a JSON file for
further analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional

import httpx


@dataclass(frozen=True)
class Step:
    """Description of a single HTTP request in a user scenario."""

    name: str
    method: str
    path: str
    payload: Optional[dict] = None


# Base scenario: mimic a user that opens the catalog, scrolls through the
# quiz list and then requests a recommendation.
DEFAULT_SCENARIO: tuple[Step, ...] = (
    Step(name="catalog", method="GET", path="/catalog"),
    Step(name="tests", method="GET", path="/tests"),
    Step(name="recommend", method="GET", path="/recommend"),
)


@dataclass
class RequestResult:
    step: str
    status_code: Optional[int]
    latency_ms: Optional[float]
    error: Optional[str]


def percentile(values: List[float], percent: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    rank = (len(values) - 1) * (percent / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1 - weight) + values[upper] * weight


async def execute_step(
    client: httpx.AsyncClient,
    step: Step,
    user_id: int,
    delay_range: tuple[float, float],
) -> RequestResult:
    # Introduce a tiny bit of jitter to avoid perfectly aligned spikes.
    if delay_range[1] > 0:
        await asyncio.sleep(random.uniform(*delay_range))

    start = time.perf_counter()
    try:
        response = await client.request(
            step.method,
            step.path,
            json=step.payload,
        )
    except Exception as exc:  # pragma: no cover - network errors vary.
        return RequestResult(
            step=step.name,
            status_code=None,
            latency_ms=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    elapsed = (time.perf_counter() - start) * 1000
    return RequestResult(
        step=step.name,
        status_code=response.status_code,
        latency_ms=elapsed,
        error=None if response.status_code < 500 else f"HTTP {response.status_code}",
    )


async def simulate_user(
    client: httpx.AsyncClient,
    scenario: Iterable[Step],
    user_id: int,
    delay_range: tuple[float, float],
) -> List[RequestResult]:
    results: List[RequestResult] = []
    for step in scenario:
        results.append(await execute_step(client, step, user_id, delay_range))
    return results


async def run_load_test(
    base_url: str,
    users: int,
    scenario: Iterable[Step],
    timeout: float,
    rate_limit: Optional[float],
    delay_range: tuple[float, float],
) -> List[RequestResult]:
    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, limits=limits) as client:
        user_tasks: List[asyncio.Task[List[RequestResult]]] = []
        interval = 0.0
        if rate_limit and rate_limit > 0:
            # Number of users spawned per second.
            interval = 1.0 / rate_limit

        for user_id in range(users):
            user_tasks.append(asyncio.create_task(simulate_user(client, scenario, user_id, delay_range)))
            if interval:
                await asyncio.sleep(interval)

        nested_results = await asyncio.gather(*user_tasks)

    results: List[RequestResult] = []
    for chunk in nested_results:
        results.extend(chunk)
    return results


def render_report(results: List[RequestResult]) -> str:
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    status_counter = Counter(r.status_code for r in results if r.status_code is not None)
    errors = [r for r in results if r.error]
    total = len(results)

    lines = [
        "=== Stress test summary ===",
        f"Requests: {total}",
        f"Successful: {total - len(errors)} | Errors: {len(errors)}",
    ]

    if latencies:
        latencies.sort()
        p50 = percentile(latencies, 50)
        p95 = percentile(latencies, 95)
        p99 = percentile(latencies, 99)
        lines.extend(
            [
                f"Latency p50: {p50:.1f} ms",
                f"Latency p95: {p95:.1f} ms",
                f"Latency p99: {p99:.1f} ms",
                f"Mean latency: {statistics.mean(latencies):.1f} ms",
            ]
        )

    if status_counter:
        lines.append("Status codes:")
        for status, count in sorted(status_counter.items()):
            lines.append(f"  {status}: {count}")

    if errors:
        lines.append("Top errors:")
        for error, count in Counter(r.error for r in errors).most_common(5):
            lines.append(f"  {error}: {count}")

    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Concurrent stress test driver")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Target service base URL")
    parser.add_argument("--users", type=int, default=500, help="Number of concurrent users to simulate")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP client timeout in seconds",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Optional spawn rate (users per second) to throttle ramp-up",
    )
    parser.add_argument(
        "--delay",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        default=(0.0, 0.1),
        help="Random delay range between consecutive steps of a user",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to dump raw request metrics as JSON",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.users <= 0:
        raise SystemExit("--users must be greater than 0")

    delay_range = tuple(sorted(args.delay))  # type: ignore[arg-type]

    try:
        results = asyncio.run(
            run_load_test(
                base_url=args.base_url,
                users=args.users,
                scenario=DEFAULT_SCENARIO,
                timeout=args.timeout,
                rate_limit=args.rate,
                delay_range=delay_range,
            )
        )
    except KeyboardInterrupt:  # pragma: no cover - manual interruption.
        print("Interrupted", file=sys.stderr)
        return 1

    print(render_report(results))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump([result.__dict__ for result in results], fp, indent=2)
        print(f"Raw metrics saved to {args.output}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
