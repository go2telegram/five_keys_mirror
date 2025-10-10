"""Простое in-memory хранилище метрик для SLO."""
from __future__ import annotations

from typing import Dict, Mapping

from asyncio import Lock

_metrics: Dict[str, float] = {
    "error_rate": 0.0,
    "revenue_drop_percent": 0.0,
}
_lock: Lock | None = None


def _get_lock() -> Lock:
    global _lock
    if _lock is None:
        _lock = Lock()
    return _lock


async def set_metric(name: str, value: float) -> None:
    async with _get_lock():
        _metrics[name] = float(value)


def get_metric(name: str, default: float | None = None) -> float | None:
    return _metrics.get(name, default)


def get_metrics_snapshot() -> Mapping[str, float]:
    # Копия значений, без блокировок — предполагаем вызов из одного треда.
    return dict(_metrics)

