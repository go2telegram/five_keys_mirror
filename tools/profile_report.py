#!/usr/bin/env python3
"""Generate Markdown reports with profiling statistics."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import math
import pathlib
import re
import sys
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Mapping

BUCKET_PATTERN = re.compile(
    r"^handler_latency_bucket\{route=\"(?P<route>[^\"]+)\",le=\"(?P<le>[^\"]+)\"\}\s+(?P<value>[-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)$"
)
SUM_PATTERN = re.compile(
    r"^handler_latency_sum\{route=\"(?P<route>[^\"]+)\"\}\s+(?P<value>[-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)$"
)
COUNT_PATTERN = re.compile(
    r"^handler_latency_count\{route=\"(?P<route>[^\"]+)\"\}\s+(?P<value>[-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)$"
)

DEFAULT_HISTORY_PATH = pathlib.Path("reports/profile_history.json")
DEFAULT_REPORT_PATH = pathlib.Path("reports/profile.md")
DEFAULT_METRICS_URL = "http://localhost:8080/metrics"
DEFAULT_WINDOW_HOURS = 24.0
DEFAULT_ALERT_MINUTES = 10
DEFAULT_OPTIMIZE_THRESHOLD_MS = 500.0


@dataclasses.dataclass
class HistogramSnapshot:
    buckets: Mapping[float, float]
    total_count: float
    total_sum: float

    def copy(self) -> "HistogramSnapshot":
        return HistogramSnapshot(dict(self.buckets), self.total_count, self.total_sum)


def parse_metrics(text: str) -> Dict[str, HistogramSnapshot]:
    """Parse histogram metrics from Prometheus exposition format."""

    buckets: Dict[str, Dict[str, float]] = {}
    sums: Dict[str, float] = {}
    counts: Dict[str, float] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        bucket_match = BUCKET_PATTERN.match(line)
        if bucket_match:
            route = bucket_match.group("route")
            buckets.setdefault(route, {})[bucket_match.group("le")] = float(bucket_match.group("value"))
            continue

        sum_match = SUM_PATTERN.match(line)
        if sum_match:
            sums[sum_match.group("route")] = float(sum_match.group("value"))
            continue

        count_match = COUNT_PATTERN.match(line)
        if count_match:
            counts[count_match.group("route")] = float(count_match.group("value"))
            continue

    snapshots: Dict[str, HistogramSnapshot] = {}
    for route, raw_buckets in buckets.items():
        snapshot_buckets: Dict[float, float] = {}
        for le_str, value in raw_buckets.items():
            upper = math.inf if le_str == "+Inf" else float(le_str)
            snapshot_buckets[upper] = value
        snapshots[route] = HistogramSnapshot(
            buckets=snapshot_buckets,
            total_count=counts.get(route, 0.0),
            total_sum=sums.get(route, 0.0),
        )

    return snapshots


def fetch_metrics(metrics_url: str) -> str:
    try:
        with urllib.request.urlopen(metrics_url) as response:
            payload = response.read().decode("utf-8")
        return payload
    except urllib.error.URLError as exc:  # pragma: no cover - network failure
        raise RuntimeError(f"Failed to fetch metrics from {metrics_url}: {exc}") from exc


def _histogram_delta(
    current: Dict[str, HistogramSnapshot],
    baseline: Dict[str, HistogramSnapshot],
) -> Dict[str, HistogramSnapshot]:
    result: Dict[str, HistogramSnapshot] = {}
    for route, latest in current.items():
        base = baseline.get(route)
        buckets: Dict[float, float] = {}
        for bound, value in latest.buckets.items():
            previous = base.buckets.get(bound, 0.0) if base else 0.0
            buckets[bound] = max(0.0, value - previous)
        total_count = latest.total_count - (base.total_count if base else 0.0)
        total_sum = latest.total_sum - (base.total_sum if base else 0.0)
        if total_count <= 0 and all(v <= 0 for v in buckets.values()):
            continue
        result[route] = HistogramSnapshot(buckets=buckets, total_count=max(total_count, 0.0), total_sum=max(total_sum, 0.0))
    return result


def _choose_baseline(
    history: List[Mapping[str, object]],
    window_start: dt.datetime,
) -> Mapping[str, object]:
    baseline = history[0]
    for entry in history:
        entry_time = dt.datetime.fromisoformat(entry["timestamp"])  # type: ignore[index]
        if entry_time <= window_start:
            baseline = entry
        else:
            break
    return baseline


def compute_window_stats(
    history: List[Mapping[str, object]],
    window_hours: float,
) -> Dict[str, Dict[str, float]]:
    if not history:
        return {}

    latest_entry = history[-1]
    latest_time = dt.datetime.fromisoformat(latest_entry["timestamp"])  # type: ignore[index]
    window_start = latest_time - dt.timedelta(hours=window_hours)

    baseline_entry = _choose_baseline(history, window_start)

    current = {
        route: HistogramSnapshot(
            {float(k): float(v) for k, v in entry["buckets"].items()},
            float(entry["total_count"]),
            float(entry["total_sum"]),
        )
        for route, entry in latest_entry["metrics"].items()  # type: ignore[union-attr]
    }
    baseline = {
        route: HistogramSnapshot(
            {float(k): float(v) for k, v in entry["buckets"].items()},
            float(entry["total_count"]),
            float(entry["total_sum"]),
        )
        for route, entry in baseline_entry["metrics"].items()  # type: ignore[union-attr]
    }

    delta = _histogram_delta(current, baseline)
    return {route: _compute_stats(snapshot) for route, snapshot in delta.items()}


def _compute_stats(snapshot: HistogramSnapshot) -> Dict[str, float]:
    count = snapshot.total_count
    avg = snapshot.total_sum / count if count else 0.0
    p95 = _estimate_quantile(snapshot.buckets, count, 0.95)
    return {"count": count, "avg": avg, "p95": p95}


def _estimate_quantile(buckets: Mapping[float, float], count: float, quantile: float) -> float:
    if not buckets or count <= 0:
        return 0.0

    target = count * quantile
    cumulative_prev = 0.0
    lower_bound = 0.0

    for upper_bound in sorted(buckets):
        cumulative = buckets[upper_bound]
        if cumulative >= target:
            bucket_count = max(cumulative - cumulative_prev, 0.0)
            if bucket_count <= 0.0:
                return upper_bound if math.isfinite(upper_bound) else lower_bound
            if not math.isfinite(upper_bound):
                return lower_bound
            ratio = (target - cumulative_prev) / bucket_count
            ratio = min(max(ratio, 0.0), 1.0)
            return lower_bound + (upper_bound - lower_bound) * ratio
        cumulative_prev = cumulative
        lower_bound = upper_bound

    return max(buckets)


def load_history(path: pathlib.Path) -> List[Mapping[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def store_history(
    path: pathlib.Path,
    history: List[Mapping[str, object]],
    new_entry: Mapping[str, object],
    keep_after: dt.timedelta,
) -> List[Mapping[str, object]]:
    history.append(new_entry)
    cutoff = dt.datetime.fromisoformat(new_entry["timestamp"]) - keep_after  # type: ignore[index]
    filtered = [entry for entry in history if dt.datetime.fromisoformat(entry["timestamp"]) >= cutoff]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as sink:
        json.dump(filtered, sink, ensure_ascii=False, indent=2)
    return filtered


def _serialize_snapshot(snapshot: Mapping[str, HistogramSnapshot]) -> Dict[str, object]:
    serialized: Dict[str, object] = {}
    for route, data in snapshot.items():
        serialized[route] = {
            "buckets": {str(bound): value for bound, value in data.buckets.items()},
            "total_count": data.total_count,
            "total_sum": data.total_sum,
        }
    return serialized


def render_markdown(
    stats: Dict[str, Dict[str, float]],
    window_hours: float,
    generated_at: dt.datetime,
    metrics_url: str,
) -> str:
    header = [
        "# Handler performance report",
        "",
        f"Window: **{window_hours:.2f}h**",
        f"Generated at: **{generated_at.isoformat()}**",
        f"Source: `{metrics_url}`",
        "",
    ]

    if not stats:
        header.append("No handler data available for the selected window.")
        return "\n".join(header)

    sorted_by_p95 = sorted(stats.items(), key=lambda item: item[1]["p95"], reverse=True)[:10]
    sorted_by_count = sorted(stats.items(), key=lambda item: item[1]["count"], reverse=True)[:10]

    def _format_row(index: int, route: str, data: Mapping[str, float]) -> str:
        count = int(data["count"])
        p95_ms = data["p95"] * 1000.0
        avg_ms = data["avg"] * 1000.0
        return f"| {index} | `{route}` | {count} | {p95_ms:.1f} | {avg_ms:.1f} |"

    lines: List[str] = header
    lines.extend(
        [
            "## Top 10 by P95",
            "| # | Handler | Count | P95 (ms) | Avg (ms) |",
            "| - | ------- | ----- | -------- | -------- |",
        ]
    )
    for idx, (route, data) in enumerate(sorted_by_p95, start=1):
        lines.append(_format_row(idx, route, data))

    lines.extend(
        [
            "",
            "## Top 10 by Count",
            "| # | Handler | Count | P95 (ms) | Avg (ms) |",
            "| - | ------- | ----- | -------- | -------- |",
        ]
    )
    for idx, (route, data) in enumerate(sorted_by_count, start=1):
        lines.append(_format_row(idx, route, data))

    return "\n".join(lines)


def _log_optimize_alerts(
    history: List[Mapping[str, object]],
    alert_minutes: float,
    threshold_ms: float,
) -> None:
    if not history:
        return

    window_hours = alert_minutes / 60.0
    stats = compute_window_stats(history, window_hours)
    for route, data in stats.items():
        p95_ms = data["p95"] * 1000.0
        if p95_ms > threshold_ms:
            logging.warning("OPTIMIZE %s p95=%.1fms over last %.0f minutes", route, p95_ms, alert_minutes)


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate profiling report from Prometheus metrics")
    parser.add_argument("--metrics-url", default=DEFAULT_METRICS_URL, help="URL of the metrics endpoint")
    parser.add_argument("--hours", type=float, default=DEFAULT_WINDOW_HOURS, help="Time window in hours")
    parser.add_argument("--history", type=pathlib.Path, default=DEFAULT_HISTORY_PATH, help="Path to history cache file")
    parser.add_argument("--report", type=pathlib.Path, default=DEFAULT_REPORT_PATH, help="Destination for the Markdown report")
    parser.add_argument(
        "--alert-minutes",
        type=float,
        default=DEFAULT_ALERT_MINUTES,
        help="Duration of sustained slowdown before emitting OPTIMIZE log",
    )
    parser.add_argument(
        "--optimize-threshold-ms",
        type=float,
        default=DEFAULT_OPTIMIZE_THRESHOLD_MS,
        help="Threshold for P95 latency in milliseconds to trigger OPTIMIZE log",
    )

    args = parser.parse_args(list(argv))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    metrics_text = fetch_metrics(args.metrics_url)
    snapshots = parse_metrics(metrics_text)
    timestamp = dt.datetime.now(dt.timezone.utc)

    serialized_snapshot = {
        "timestamp": timestamp.isoformat(),
        "metrics": _serialize_snapshot(snapshots),
    }

    keep_hours = max(args.hours * 2.0, args.alert_minutes / 60.0 * 4.0, 24.0)
    history = load_history(args.history)
    history = store_history(args.history, history, serialized_snapshot, dt.timedelta(hours=keep_hours))

    stats = compute_window_stats(history, args.hours)
    markdown = render_markdown(stats, args.hours, timestamp, args.metrics_url)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as sink:
        sink.write(markdown)

    print(markdown)

    _log_optimize_alerts(history, args.alert_minutes, args.optimize_threshold_ms)

    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    sys.exit(main(sys.argv[1:]))
