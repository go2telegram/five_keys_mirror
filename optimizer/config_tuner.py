"""Utilities for adaptive configuration tuning under load.

This module implements a lightweight grid-search based optimizer that
continuously collects performance metrics and converges on the best
configuration according to the observed throughput/latency/error rate
profile.  The implementation is intentionally dependency-light so it can be
used both inside scheduled jobs and ad-hoc scripts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

__all__ = [
    "ConfigTuner",
    "JSONConfigRepository",
]


@dataclass(slots=True)
class JSONConfigRepository:
    """Simple helper that persists runtime parameters to a JSON file.

    Parameters
    ----------
    path:
        Location of the JSON file that should be used for persistence.
    defaults:
        Mapping with default values that will be merged with the stored data.
    """

    path: Path
    defaults: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - filesystem guard
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        """Return current configuration (stored or defaults)."""

        if not self.path.exists():
            return dict(self.defaults)
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(self.defaults)
        merged = dict(self.defaults)
        for key, value in data.items():
            merged[key] = value
        return merged

    def write(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Persist the provided configuration and return it."""

        payload = dict(self.defaults)
        payload.update(values)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        return payload


class ConfigTuner:
    """Adaptive configuration tuner based on grid-search exploration.

    The tuner alternates between *exploration* (iterating through the supplied
    parameter grid) and *exploitation* (sticking to the best performing
    configuration observed so far).  Performance is measured via metrics that
    describe throughput, latency, error rate and memory usage.

    The typical usage pattern is::

        repo = JSONConfigRepository(Path("optimizer/runtime_config.json"), defaults)
        tuner = ConfigTuner(
            base_config=defaults,
            search_space={"BATCH_SIZE": [4, 8, 16]},
            config_provider=repo.read,
            config_applier=repo.write,
        )
        tuner.run_iteration(metrics_sample)
    """

    def __init__(
        self,
        *,
        base_config: Mapping[str, Any],
        search_space: Mapping[str, Sequence[Any]],
        config_provider: Callable[[], Mapping[str, Any]],
        config_applier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
        state_path: Path | str = Path("optimizer/config_tuner_state.json"),
        log_path: Path | str = Path("optimizer/config_tuner.log"),
        min_samples: int = 3,
        improvement_threshold: float = 0.1,
        target_latency_ms: float = 1000.0,
        memory_budget_mb: float | None = None,
        error_rate_weight: float = 5.0,
        memory_penalty_weight: float = 0.5,
    ) -> None:
        self.base_config = dict(base_config)
        self.search_space = {name: list(options) for name, options in search_space.items()}
        self.config_provider = config_provider
        self.config_applier = config_applier
        self.min_samples = max(1, int(min_samples))
        self.improvement_threshold = max(0.0, improvement_threshold)
        self.target_latency_ms = max(1.0, float(target_latency_ms))
        self.memory_budget_mb = float(memory_budget_mb) if memory_budget_mb is not None else None
        self.error_rate_weight = max(0.0, float(error_rate_weight))
        self.memory_penalty_weight = max(0.0, float(memory_penalty_weight))

        self.state_path = Path(state_path)
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("config_tuner")
        if not self._logger.handlers:
            handler = logging.FileHandler(self.log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

        self.state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_iteration(self, metrics: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Process a metrics sample and potentially apply a new configuration.

        Parameters
        ----------
        metrics:
            Optional mapping with the latest performance sample.  Expected keys
            are ``throughput``, ``latency_ms``, ``error_rate`` and
            ``memory_mb``.  Missing keys will simply be ignored.

        Returns
        -------
        dict | None
            The configuration that was applied during this iteration (if any).
        """

        current_config = self._normalize_config(self.config_provider())
        current_key = self._config_key(current_config)
        entry = None
        if metrics:
            entry = self._record_metrics(current_config, metrics)
            if (
                self.state["pending"]
                and self.state["pending"][0] == current_key
                and entry["count"] >= self.min_samples
            ):
                self.state["pending"].pop(0)

        candidate, reason = self._select_next_config(current_key)
        applied_config: dict[str, Any] | None = None
        if candidate:
            candidate_key = self._config_key(candidate)
            if reason == "pending":
                # Remove from pending before applying to avoid re-selection on
                # subsequent iterations.
                if self.state["pending"] and self.state["pending"][0] == candidate_key:
                    self.state["pending"].pop(0)
            self.config_applier(candidate)
            self.state["last_applied"] = {
                "config": candidate_key,
                "reason": reason,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            applied_config = candidate
            self._logger.info("applied config reason=%s config=%s", reason, candidate)
        self._save_state()
        return applied_config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalize_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(self.base_config)
        merged.update({k: config.get(k, merged.get(k)) for k in self.search_space})
        return merged

    def _normalize_metrics(self, metrics: Mapping[str, Any]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key in ("throughput", "latency_ms", "error_rate", "memory_mb"):
            value = metrics.get(key)
            if value is None:
                continue
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _record_metrics(self, config: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
        sample = self._normalize_metrics(metrics)
        key = self._config_key(config)
        history: MutableMapping[str, MutableMapping[str, Any]] = self.state.setdefault("history", {})
        entry = history.setdefault(
            key,
            {
                "count": 0,
                "avg_throughput": 0.0,
                "avg_latency": 0.0,
                "avg_error_rate": 0.0,
                "avg_memory": None,
                "score": 0.0,
            },
        )
        prev_count = entry["count"]
        entry["count"] = prev_count + 1
        entry["avg_throughput"] = self._update_mean(entry["avg_throughput"], sample.get("throughput"), prev_count)
        entry["avg_latency"] = self._update_mean(entry["avg_latency"], sample.get("latency_ms"), prev_count)
        entry["avg_error_rate"] = self._update_mean(entry["avg_error_rate"], sample.get("error_rate"), prev_count)
        if sample.get("memory_mb") is not None:
            entry["avg_memory"] = self._update_mean(
                entry.get("avg_memory") or 0.0, sample.get("memory_mb"), prev_count
            )
        entry["score"] = self._compute_score(entry)
        entry["last_sample"] = datetime.now(timezone.utc).isoformat()
        self._logger.info(
            "metrics config=%s throughput=%.3f latency=%.3f error_rate=%.4f score=%.5f",
            config,
            sample.get("throughput", float("nan")),
            sample.get("latency_ms", float("nan")),
            sample.get("error_rate", float("nan")),
            entry["score"],
        )
        return dict(entry)

    def _select_next_config(self, current_key: str) -> tuple[dict[str, Any] | None, str | None]:
        if self.state["pending"]:
            candidate_key = self.state["pending"][0]
            if candidate_key != current_key:
                return self._decode_config(candidate_key), "pending"
            return None, None
        best = self._best_config()
        if not best:
            return None, None
        best_key, best_score = best
        if best_key == current_key:
            return None, None
        current_entry = self.state.get("history", {}).get(current_key)
        current_score = current_entry.get("score") if current_entry else None
        if current_score is None:
            return self._decode_config(best_key), "best"
        if best_score >= current_score * (1.0 + self.improvement_threshold):
            return self._decode_config(best_key), "best"
        return None, None

    def _best_config(self) -> tuple[str, float] | None:
        history = self.state.get("history", {})
        candidates = [
            (key, entry)
            for key, entry in history.items()
            if entry.get("count", 0) >= self.min_samples
        ]
        if not candidates:
            return None
        best_key, best_entry = max(candidates, key=lambda item: item[1].get("score", float("-inf")))
        return best_key, float(best_entry.get("score", 0.0))

    def _compute_score(self, entry: Mapping[str, Any]) -> float:
        throughput = float(entry.get("avg_throughput") or 0.0)
        latency = float(entry.get("avg_latency") or self.target_latency_ms)
        error_rate = max(0.0, float(entry.get("avg_error_rate") or 0.0))
        latency_factor = self.target_latency_ms / max(latency, 1.0)
        error_factor = max(0.0, 1.0 - error_rate * self.error_rate_weight)
        score = throughput * latency_factor * error_factor
        if self.memory_budget_mb is not None:
            avg_memory = entry.get("avg_memory")
            if avg_memory is not None:
                avg_memory = float(avg_memory)
                if avg_memory > self.memory_budget_mb:
                    overuse_ratio = (avg_memory - self.memory_budget_mb) / max(self.memory_budget_mb, 1.0)
                    score -= overuse_ratio * self.memory_penalty_weight * max(throughput, 1.0)
        return score

    def _update_mean(self, prev_mean: Any, new_value: Any, prev_count: int) -> float:
        if new_value is None:
            return float(prev_mean or 0.0)
        if prev_count <= 0 or prev_mean is None:
            return float(new_value)
        return (float(prev_mean) * prev_count + float(new_value)) / (prev_count + 1)

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        else:
            data = {}
        data.setdefault("history", {})
        data.setdefault("pending", self._initial_pending())
        data.setdefault("last_applied", None)
        return data

    def _save_state(self) -> None:
        payload = json.dumps(self.state, indent=2, sort_keys=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(payload, "utf-8")

    def _initial_pending(self) -> list[str]:
        keys = list(self.search_space.keys())
        grid: list[str] = []
        if not keys:
            return grid
        for combo in product(*(self.search_space[k] for k in keys)):
            config = {key: combo[idx] for idx, key in enumerate(keys)}
            grid.append(self._config_key(config))
        base_key = self._config_key(self.base_config)
        if base_key not in grid:
            grid.insert(0, base_key)
        return grid

    def _config_key(self, config: Mapping[str, Any]) -> str:
        normalized = {k: config.get(k, self.base_config.get(k)) for k in sorted(self.search_space)}
        return json.dumps(normalized, sort_keys=True)

    def _decode_config(self, key: str) -> dict[str, Any]:
        try:
            data = json.loads(key)
        except json.JSONDecodeError:
            return dict(self.base_config)
        merged = dict(self.base_config)
        merged.update(data)
        return merged
