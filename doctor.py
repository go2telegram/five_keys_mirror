"""Service health checks and reporting utilities for the bot runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from ipaddress import IPv4Address, IPv6Address, ip_address
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Final

import httpx
from prometheus_client.parser import text_string_to_metric_families

from app.config import settings


DEFAULT_TIMEOUT: Final[float] = 5.0


@dataclass(slots=True)
class MetricsSnapshot:
    payload: str
    summary: Dict[str, Any]


def _client_host_for_default() -> str:
    """Return a loopback-safe host for default HTTP targets."""

    host = settings.WEB_HOST

    try:
        ip = ip_address(host)
    except ValueError:
        # Non-IP hosts (e.g. domain names) are assumed to be routable as-is.
        return host

    if ip.is_unspecified:
        ip = IPv6Address("::1") if ip.version == 6 else IPv4Address("127.0.0.1")

    return f"[{ip.compressed}]" if ip.version == 6 else ip.compressed


async def check_metrics_endpoint() -> MetricsSnapshot:
    metrics_host = _client_host_for_default()
    metrics_url = os.getenv(
        "METRICS_URL",
        f"http://{metrics_host}:{settings.WEB_PORT}/metrics",
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

    summary: Dict[str, Any] = {}
    updates_total: dict[str, float] = defaultdict(float)
    errors_total: dict[str, float] = defaultdict(float)
    latency_sum: dict[str, float] = defaultdict(float)
    latency_count: dict[str, float] = defaultdict(float)

    for family in text_string_to_metric_families(payload):
        if family.name == "bot_uptime_seconds":
            for sample in family.samples:
                summary["uptime_seconds"] = sample.value
        elif family.name == "bot_active_users":
            for sample in family.samples:
                summary["active_users"] = sample.value
        elif family.name == "bot_updates_total":
            for sample in family.samples:
                update_type = sample.labels.get("update_type", "unknown")
                updates_total[update_type] += sample.value
        elif family.name == "bot_update_errors_total":
            for sample in family.samples:
                update_type = sample.labels.get("update_type", "unknown")
                errors_total[update_type] += sample.value
        elif family.name == "bot_update_latency_seconds":
            for sample in family.samples:
                update_type = sample.labels.get("update_type", "unknown")
                metric_name = sample.name.split("_")[-1]
                if metric_name == "sum":
                    latency_sum[update_type] += sample.value
                elif metric_name == "count":
                    latency_count[update_type] += sample.value

    per_update_type: Dict[str, Dict[str, float]] = {}
    for update_type in set(
        list(updates_total.keys())
        | set(errors_total.keys())
        | set(latency_sum.keys())
        | set(latency_count.keys())
    ):
        total = updates_total.get(update_type, 0.0)
        errors = errors_total.get(update_type, 0.0)
        count = latency_count.get(update_type, 0.0)
        sum_latency = latency_sum.get(update_type, 0.0)
        average_latency = sum_latency / count if count else 0.0
        per_update_type[update_type] = {
            "updates_total": total,
            "errors_total": errors,
            "latency_count": count,
            "latency_sum": sum_latency,
            "latency_avg": average_latency,
        }

    summary["per_update_type"] = per_update_type
    summary["updates_total"] = sum(updates_total.values())
    summary["errors_total"] = sum(errors_total.values())

    return MetricsSnapshot(payload=payload, summary=summary)


async def check_ping_endpoint() -> Dict[str, Any]:
    ping_host = _client_host_for_default()
    ping_url = os.getenv(
        "PING_URL",
        f"http://{ping_host}:{settings.WEB_PORT}/ping",
    )

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.get(ping_url)

    if response.status_code != 200:
        raise SystemExit(f"/ping health-check failed: HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:  # noqa: PERF203 - explicit failure message
        raise SystemExit(f"/ping returned invalid JSON: {exc}") from exc

    if payload.get("status") != "ok":
        detail = payload.get("detail")
        raise SystemExit(f"/ping unhealthy: {detail}")

    recovery = payload.get("recovery", {}) or {}
    if recovery.get("count"):
        print("service recovered", flush=True)
    return payload


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Persist a JSON health report (location can be customised via --report-dir)",
    )
    parser.add_argument(
        "--report-dir",
        default=os.getenv("DOCTOR_REPORT_DIR", "reports/doctor"),
        help="Directory where doctor JSON reports are stored (default: reports/doctor)",
    )
    return parser


async def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    metrics = await check_metrics_endpoint()
    ping_payload = await check_ping_endpoint()

    if args.report:
        report_dir = Path(args.report_dir).expanduser().resolve()
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc)
        report_path = report_dir / f"doctor_report_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
        report_payload = {
            "generated_at": timestamp.isoformat(),
            "ping": ping_payload,
            "metrics": metrics.summary,
            "metrics_raw": metrics.payload,
        }
        report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"doctor report saved to {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
