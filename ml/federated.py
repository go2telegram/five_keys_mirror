"""Federated learning helpers for exchanging model weights between bot instances."""
from __future__ import annotations

import asyncio
import logging
import pickle
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import httpx

logger = logging.getLogger(__name__)

Weights = Mapping[str, list[float]]
Metrics = Mapping[str, float]


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_weights(path: Path) -> Weights:
    """Load serialized model weights from ``path``."""
    if not path.exists():
        logger.debug("Weights file %s does not exist", path)
        return {}
    with path.open("rb") as fp:
        data = pickle.load(fp)
    if not isinstance(data, Mapping):
        raise TypeError(f"Weights at {path} must be a mapping, got {type(data)!r}")
    return dict(data)


def save_weights(path: Path, weights: Mapping[str, Iterable[float]]) -> None:
    """Persist model ``weights`` to ``path`` in pickle format."""
    _ensure_parent_dir(path)
    serializable = {key: [float(v) for v in values] for key, values in weights.items()}
    with path.open("wb") as fp:
        pickle.dump(serializable, fp)
    logger.debug("Saved %d layers to %s", len(serializable), path)


def fed_avg(weight_sets: Iterable[Mapping[str, Iterable[float]]]) -> dict[str, list[float]]:
    """
    Perform FedAvg aggregation over a collection of ``weight_sets``.

    Each weight set is expected to be a mapping of layer name to an iterable of
    numerical values. The result is a dictionary with the averaged weights for
    every layer that appears in at least one client submission. Layers missing
    from some clients are averaged across the clients that provided them.
    """
    totals: dict[str, list[float]] = {}
    counts: dict[str, int] = {}

    for weights in weight_sets:
        for layer_name, values in weights.items():
            vector = [float(v) for v in values]
            if not vector:
                continue
            if layer_name not in totals:
                totals[layer_name] = [0.0] * len(vector)
                counts[layer_name] = 0
            if len(totals[layer_name]) != len(vector):
                raise ValueError(
                    f"Layer {layer_name} has inconsistent shape across clients"
                )
            totals[layer_name] = [a + b for a, b in zip(totals[layer_name], vector)]
            counts[layer_name] += 1

    averaged: dict[str, list[float]] = {}
    for layer_name, summed in totals.items():
        count = counts[layer_name]
        if count:
            averaged[layer_name] = [v / count for v in summed]

    return averaged


def aggregate_client_payloads(payloads: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[float]], Metrics]:
    """Aggregate client payloads received by the federated server."""
    weight_sets = []
    accuracies: list[float] = []

    for payload in payloads:
        weights = payload.get("weights") or {}
        if isinstance(weights, Mapping):
            weight_sets.append(weights)
        metrics = payload.get("metrics") or {}
        if isinstance(metrics, Mapping) and "accuracy" in metrics:
            try:
                accuracies.append(float(metrics["accuracy"]))
            except (TypeError, ValueError):
                logger.debug("Skipping non-numeric accuracy from payload: %r", metrics)

    aggregated_weights = fed_avg(weight_sets)
    aggregated_metrics: Metrics = {}
    if accuracies:
        aggregated_metrics["accuracy"] = sum(accuracies) / len(accuracies)

    return aggregated_weights, aggregated_metrics


def _default_client_id() -> str:
    try:
        hostname = socket.gethostname()
    except Exception:  # pragma: no cover - extremely unlikely
        hostname = "unknown"
    return hostname


@dataclass(slots=True)
class FederatedLearningClient:
    """Client responsible for synchronising local model weights with the server."""

    server_url: str
    client_id: str | None = None
    local_model_path: Path = Path("models/local.pkl")
    merged_model_path: Path = Path("models/_merged.pkl")
    evaluator: Callable[[Mapping[str, Iterable[float]]], float] | None = None
    timeout: float = 30.0

    async def sync(self) -> dict[str, Any]:
        """Synchronise local weights with the federated server."""
        if not self.server_url:
            raise ValueError("server_url must be configured for federated sync")

        client_id = self.client_id or _default_client_id()
        local_weights = load_weights(self.local_model_path)
        payload: dict[str, Any] = {"client_id": client_id, "weights": local_weights}

        local_accuracy: float | None = None
        if self.evaluator and local_weights:
            local_accuracy = self.evaluator(local_weights)
            payload["metrics"] = {"accuracy": local_accuracy}

        endpoint = f"{self.server_url.rstrip('/')}/sync_model"
        logger.info("Syncing %s with federated server %s", client_id, endpoint)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()

        merged_weights = data.get("weights") or data.get("aggregated_weights") or {}
        if not isinstance(merged_weights, Mapping):
            raise TypeError("Server response must include mapping under 'weights'")

        save_weights(self.merged_model_path, merged_weights)  # type: ignore[arg-type]

        metrics = data.get("metrics") or {}
        aggregated_accuracy = None
        if isinstance(metrics, Mapping):
            for key in ("aggregated_accuracy", "global_accuracy", "accuracy"):
                if key in metrics:
                    try:
                        aggregated_accuracy = float(metrics[key])
                        break
                    except (TypeError, ValueError):
                        logger.debug("Server metric %s is not numeric: %r", key, metrics[key])

        if aggregated_accuracy is None and self.evaluator and merged_weights:
            aggregated_accuracy = self.evaluator(merged_weights)

        result = {
            "client_id": client_id,
            "saved_path": str(self.merged_model_path),
            "local_accuracy": local_accuracy,
            "aggregated_accuracy": aggregated_accuracy,
            "raw_response": data,
        }
        logger.info("Federated sync finished for %s", client_id)
        return result

    def sync_blocking(self) -> dict[str, Any]:
        """Run :meth:`sync` synchronously, useful for CLI scripts."""
        return asyncio.run(self.sync())
