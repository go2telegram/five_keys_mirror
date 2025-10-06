from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from statistics import pstdev
from typing import Iterable, Sequence

Z_THRESHOLD = 3.0


def _alpha(sample_size: int) -> float:
    if sample_size <= 1:
        return 1.0
    # классическая формула для EWMA: alpha = 2 / (n + 1)
    return min(1.0, max(0.01, 2.0 / (sample_size + 1)))


@dataclass(slots=True)
class TimeSeries:
    slug: str
    name: str
    points: list[tuple[dt.datetime, float]]
    labels: dict[str, str] | None = None

    def cleaned(self) -> list[tuple[dt.datetime, float]]:
        cleaned_points: list[tuple[dt.datetime, float]] = []
        for ts, value in sorted(self.points, key=lambda item: item[0]):
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric):
                continue
            cleaned_points.append((ts, numeric))
        return cleaned_points


@dataclass(slots=True)
class Anomaly:
    metric: str
    slug: str
    window: str
    timestamp: dt.datetime
    value: float
    baseline: float
    z_score: float
    direction: str
    labels: dict[str, str] | None = None

    @property
    def change_pct(self) -> float | None:
        if self.baseline == 0:
            return None
        return (self.value - self.baseline) / self.baseline * 100

    @property
    def kind(self) -> str:
        return f"{self.slug}:{self.window}"


def _ewma(values: Sequence[float], alpha: float) -> list[float]:
    smoothed: list[float] = []
    prev = values[0]
    smoothed.append(prev)
    for value in values[1:]:
        prev = alpha * value + (1 - alpha) * prev
        smoothed.append(prev)
    return smoothed


def _residual_std(values: Sequence[float], baselines: Sequence[float]) -> float:
    residuals = [value - baseline for value, baseline in zip(values, baselines)]
    if len(residuals) < 3:
        return 0.0
    try:
        return pstdev(residuals[1:])  # отбрасываем стартовое значение
    except Exception:
        return 0.0


def detect(timeseries: TimeSeries, window: str = "1h", z_threshold: float = Z_THRESHOLD) -> list[Anomaly]:
    points = timeseries.cleaned()
    if len(points) < 4:
        return []

    timestamps, values = zip(*points)
    alpha = _alpha(len(values))
    smoothed = _ewma(values, alpha)
    baselines = list(smoothed)
    for idx in range(len(baselines) - 1, 0, -1):
        baselines[idx] = smoothed[idx - 1]
    std = _residual_std(values, baselines)
    if std == 0:
        return []

    latest: Anomaly | None = None
    for idx in range(2, len(values)):
        baseline = baselines[idx]
        residual = values[idx] - baseline
        z = residual / std if std else 0.0
        if abs(z) < z_threshold:
            continue
        direction = "up" if z > 0 else "down"
        latest = Anomaly(
            metric=timeseries.name,
            slug=timeseries.slug,
            window=window,
            timestamp=timestamps[idx],
            value=values[idx],
            baseline=baseline,
            z_score=z,
            direction=direction,
            labels=timeseries.labels,
        )

    return [latest] if latest else []


def _format_change(anomaly: Anomaly) -> str:
    pct = anomaly.change_pct
    if pct is None:
        return f"{anomaly.value:.2f}"
    sign = "↑" if anomaly.direction == "up" else "↓"
    return f"{sign} {pct:+.1f}%"


def report(anomalies: Iterable[Anomaly]) -> str:
    anomalies_list = list(anomalies)
    header = "📊 Metrics health"
    if not anomalies_list:
        return f"{header}\nВсе метрики в норме."

    latest_by_kind: dict[str, Anomaly] = {}
    for anomaly in anomalies_list:
        key = (anomaly.metric, anomaly.kind)
        prev = latest_by_kind.get(key)
        if not prev or anomaly.timestamp > prev.timestamp:
            latest_by_kind[key] = anomaly

    sorted_anomalies = sorted(
        latest_by_kind.values(),
        key=lambda item: (-abs(item.z_score), item.metric, item.window),
    )

    lines = []
    for anomaly in sorted_anomalies:
        change_str = _format_change(anomaly)
        baseline_str = f"{anomaly.baseline:.2f}"
        value_str = f"{anomaly.value:.2f}"
        time_str = anomaly.timestamp.strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"• {anomaly.metric} ({anomaly.window}) {change_str} → {value_str} (baseline {baseline_str}) — z={anomaly.z_score:.1f} @ {time_str} UTC"
        )

    return f"{header}\n" + "\n".join(lines)
