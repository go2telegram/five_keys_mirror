"""Helpers to persist and expose model telemetry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

METRICS_DIR = Path("metrics")
MODELS_PATH = METRICS_DIR / "models.json"


def _ensure_dir() -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)


def read_model_metrics() -> Dict[str, Any]:
    """Return the stored model metrics (may be empty)."""

    if not MODELS_PATH.exists():
        return {}
    try:
        return json.loads(MODELS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def update_model_metric(
    model_name: str,
    model_version: int,
    accuracy: float,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Persist metrics for a specific model."""

    payload = read_model_metrics()
    record = {
        "model_version": int(model_version),
        "model_accuracy": round(float(accuracy), 4),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if metadata:
        record.update(metadata)

    payload[model_name] = record
    _ensure_dir()
    MODELS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def metrics_payload() -> Dict[str, Any]:
    """Return payload suitable for the /metrics endpoint."""

    return {"models": read_model_metrics()}
