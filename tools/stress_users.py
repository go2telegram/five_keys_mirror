"""Simple concurrent stress-test runner for the Five Keys bot.

The script simulates dozens of concurrent users that sequentially
exercise the most frequently used public HTTP endpoints: catalog
browsing, energy test navigation and recommendation retrieval.  It is
intentionally lightweight so it can be executed from a developer
workstation or CI against a staging environment while still delivering
actionable latency percentiles.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
    Step(name="recommend", method="GET", path="/recommend"),
    Step(name="tests_energy", method="GET", path="/tests/energy"),
    Step(name="catalog", method="GET", path="/catalog"),
)

MAX_HISTORY_LENGTH = 90


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
    error_message: Optional[str] = None
    if response.status_code >= 400:
        error_message = f"HTTP {response.status_code}"

    return RequestResult(
        step=step.name,
        status_code=response.status_code,
        latency_ms=elapsed,
        error=error_message,
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


def _is_error(result: RequestResult) -> bool:
    if result.error:
        return True
    if result.status_code is None:
        return True
    return result.status_code >= 400


def _counter_to_dict(counter: Counter[int]) -> Dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def _latency_summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}

    sorted_values = sorted(values)
    return {
        "p50": percentile(sorted_values, 50),
        "p95": percentile(sorted_values, 95),
        "p99": percentile(sorted_values, 99),
        "mean": statistics.mean(sorted_values),
    }


def summarize_results(
    results: List[RequestResult],
    base_url: str,
    users: int,
    scenario_steps: List[str],
) -> Dict[str, Any]:
    total = len(results)
    status_counter = Counter(r.status_code for r in results if r.status_code is not None)
    errors = [r for r in results if _is_error(r)]
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]

    per_step_results: Dict[str, List[RequestResult]] = {name: [] for name in scenario_steps}
    for result in results:
        per_step_results.setdefault(result.step, []).append(result)

    per_step_summary: Dict[str, Dict[str, Any]] = {}
    for name, step_results in per_step_results.items():
        step_latencies = [r.latency_ms for r in step_results if r.latency_ms is not None]
        step_errors = sum(1 for r in step_results if _is_error(r))
        step_status_counter = Counter(r.status_code for r in step_results if r.status_code is not None)
        per_step_summary[name] = {
            "requests": len(step_results),
            "success": len(step_results) - step_errors,
            "errors": step_errors,
            "latency": _latency_summary(step_latencies),
            "status_codes": _counter_to_dict(step_status_counter),
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "users": users,
        "requests": total,
        "success": total - len(errors),
        "errors": len(errors),
        "latency": _latency_summary(latencies),
        "status_codes": _counter_to_dict(status_counter),
        "per_step": per_step_summary,
    }


def render_report(summary: Dict[str, Any]) -> str:
    lines = [
        "=== Stress test summary ===",
        f"Requests: {summary['requests']}",
        f"Successful: {summary['success']} | Errors: {summary['errors']}",
    ]

    latency = summary.get("latency", {})
    if latency:
        lines.extend(
            [
                f"Latency p50: {latency.get('p50', 0.0):.1f} ms",
                f"Latency p95: {latency.get('p95', 0.0):.1f} ms",
                f"Latency p99: {latency.get('p99', 0.0):.1f} ms",
                f"Mean latency: {latency.get('mean', 0.0):.1f} ms",
            ]
        )

    status_codes: Dict[str, int] = summary.get("status_codes", {})
    if status_codes:
        lines.append("Status codes:")
        for status, count in status_codes.items():
            lines.append(f"  {status}: {count}")

    if summary.get("errors"):
        per_step = summary.get("per_step", {})
        lines.append("Errors by step:")
        for step_name, payload in per_step.items():
            if payload.get("errors"):
                lines.append(f"  {step_name}: {payload['errors']}")

    return "\n".join(lines)


def _load_history(path: Path) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        return payload["runs"]
    return []


def _render_markdown(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "# Load test report\n\nНет данных о прогонах нагрузочного теста."

    latest = history[-1]
    lines = [
        "# Load test report",
        "",
        f"**Timestamp:** {latest['timestamp']}",
        f"**Base URL:** {latest['base_url']}",
        f"**Concurrent users:** {latest['users']}",
        "",
        "## Latest run",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Requests | {latest['requests']} |",
        f"| Success | {latest['success']} |",
        f"| Errors | {latest['errors']} |",
        f"| Latency p50 (ms) | {latest['latency']['p50']:.2f} |",
        f"| Latency p95 (ms) | {latest['latency']['p95']:.2f} |",
        f"| Latency p99 (ms) | {latest['latency']['p99']:.2f} |",
        f"| Mean latency (ms) | {latest['latency']['mean']:.2f} |",
    ]

    per_step = latest.get("per_step", {})
    if per_step:
        lines.extend([
            "",
            "### Per-step latency",
            "",
            "| Step | Requests | Errors | p50 (ms) | p95 (ms) |",
            "| --- | --- | --- | --- | --- |",
        ])
        for step_name, payload in per_step.items():
            latency = payload.get("latency", {})
            lines.append(
                "| {} | {} | {} | {:.2f} | {:.2f} |".format(
                    step_name,
                    payload.get("requests", 0),
                    payload.get("errors", 0),
                    latency.get("p50", 0.0),
                    latency.get("p95", 0.0),
                )
            )

    lines.extend([
        "",
        "## History (latest 10 runs)",
        "",
        "| Timestamp | p50 (ms) | p95 (ms) | Errors | Requests |",
        "| --- | --- | --- | --- | --- |",
    ])

    for entry in history[-10:]:
        latency = entry.get("latency", {})
        lines.append(
            "| {} | {:.2f} | {:.2f} | {} | {} |".format(
                entry.get("timestamp", "—"),
                latency.get("p50", 0.0),
                latency.get("p95", 0.0),
                entry.get("errors", 0),
                entry.get("requests", 0),
            )
        )

    return "\n".join(lines)


def _write_reports(summary: Dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "load.json"
    history = _load_history(json_path)
    history.append(summary)
    if len(history) > MAX_HISTORY_LENGTH:
        history = history[-MAX_HISTORY_LENGTH:]
    json_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    markdown_path = report_dir / "load.md"
    markdown_path.write_text(_render_markdown(history), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Concurrent stress test driver")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Target service base URL")
    parser.add_argument("--users", type=int, default=50, help="Number of concurrent users to simulate")
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
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("build/reports"),
        help="Directory to store aggregated reports (set to '-' to disable)",
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

    scenario_steps = [step.name for step in DEFAULT_SCENARIO]
    summary = summarize_results(results, args.base_url, args.users, scenario_steps)
    print(render_report(summary))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump([result.__dict__ for result in results], fp, indent=2)
        print(f"Raw metrics saved to {args.output}")

    report_dir: Optional[Path]
    if args.report_dir == Path("-"):
        report_dir = None
    else:
        report_dir = args.report_dir

    if report_dir is not None:
        _write_reports(summary, report_dir)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
