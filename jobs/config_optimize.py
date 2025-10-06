"""Background job that continuously tunes runtime configuration."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Mapping

import httpx

from app.config import settings
from optimizer.config_tuner import ConfigTuner, JSONConfigRepository

_LOGGER = logging.getLogger("config_optimizer_job")
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)


def _parse_int_list(csv: str, fallback: list[int]) -> list[int]:
    values: list[int] = []
    for raw in csv.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            values.append(int(raw))
        except ValueError:
            continue
    return values or list(fallback)


BATCH_CHOICES = _parse_int_list(settings.OPTIMIZER_BATCH_CHOICES, [4, 8, 16])
TIMEOUT_CHOICES = _parse_int_list(settings.OPTIMIZER_TIMEOUT_CHOICES, [8000, 12000, 16000])
MEMORY_CHOICES = _parse_int_list(settings.OPTIMIZER_MEMORY_CHOICES, [512, 768, 1024])

DEFAULT_CONFIG = {
    "BATCH_SIZE": BATCH_CHOICES[min(len(BATCH_CHOICES) // 2, len(BATCH_CHOICES) - 1)],
    "TIMEOUT_MS": TIMEOUT_CHOICES[min(len(TIMEOUT_CHOICES) // 2, len(TIMEOUT_CHOICES) - 1)],
    "MEMORY_LIMIT_MB": MEMORY_CHOICES[min(len(MEMORY_CHOICES) // 2, len(MEMORY_CHOICES) - 1)],
}

_CONFIG_REPO = JSONConfigRepository(Path("optimizer/runtime_config.json"), DEFAULT_CONFIG)
_TUNER = ConfigTuner(
    base_config=DEFAULT_CONFIG,
    search_space={
        "BATCH_SIZE": BATCH_CHOICES,
        "TIMEOUT_MS": TIMEOUT_CHOICES,
        "MEMORY_LIMIT_MB": MEMORY_CHOICES,
    },
    config_provider=_CONFIG_REPO.read,
    config_applier=_CONFIG_REPO.write,
    min_samples=settings.OPTIMIZER_MIN_SAMPLES,
    improvement_threshold=settings.OPTIMIZER_REQUIRED_IMPROVEMENT,
    target_latency_ms=settings.OPTIMIZER_TARGET_LATENCY_MS,
    memory_budget_mb=settings.OPTIMIZER_MEMORY_BUDGET_MB,
    state_path=Path("optimizer/config_tuner_state.json"),
    log_path=Path("optimizer/config_tuner.log"),
)


async def _fetch_metrics() -> Mapping[str, float] | None:
    url = settings.OPTIMIZER_METRICS_URL
    timeout = settings.OPTIMIZER_HTTP_TIMEOUT
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failures are non-deterministic
        _LOGGER.warning("config optimizer failed to fetch metrics: %s", exc)
        return None
    return _coerce_metrics(response)


def _coerce_metrics(response: httpx.Response) -> Mapping[str, float]:
    body = response.text
    try:
        data = json.loads(body)
        if isinstance(data, Mapping):
            return {k: float(v) for k, v in data.items() if _is_number(v)}
    except json.JSONDecodeError:
        pass
    metrics: dict[str, float] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        name, value = parts
        if _is_number(value):
            metrics[name] = float(value)
    return metrics


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _map_metrics(raw: Mapping[str, float]) -> Mapping[str, float]:
    aliases = {
        "throughput": [
            "bot_requests_per_second",
            "requests_per_second",
            "throughput",
            "worker_throughput",
        ],
        "latency_ms": [
            "latency_ms",
            "avg_latency_ms",
            "p95_latency_ms",
            "latency",
        ],
        "error_rate": [
            "error_rate",
            "errors_per_request",
            "failure_ratio",
        ],
        "memory_mb": [
            "memory_mb",
            "rss_mb",
            "memory_usage_mb",
        ],
    }
    mapped: dict[str, float] = {}
    for target, candidates in aliases.items():
        for name in candidates:
            if name in raw:
                mapped[target] = float(raw[name])
                break
    return mapped


async def run_config_optimizer() -> dict[str, Any] | None:
    """Entrypoint for APScheduler to run optimization."""

    if not settings.ENABLE_SELF_OPTIMIZATION:
        return None
    metrics_raw = await _fetch_metrics()
    metrics = _map_metrics(metrics_raw or {}) if metrics_raw else None
    applied = _TUNER.run_iteration(metrics)
    if applied:
        _LOGGER.info("config optimizer applied new config: %s", applied)
    return applied


async def ensure_optimizer_loop() -> None:
    """Run optimizer forever with the configured interval.

    This helper is useful for standalone scripts/tests when the scheduler is
    not available.
    """

    interval = max(5, settings.OPTIMIZER_INTERVAL_SECONDS)
    while True:
        await run_config_optimizer()
        await asyncio.sleep(interval)
