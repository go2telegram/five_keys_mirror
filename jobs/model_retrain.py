"""Cron-friendly entry point to retrain recommendation models."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:  # pragma: no cover - fallback for CLI environments without .env
    from app.config import settings
except Exception as exc:  # noqa: BLE001 - we want graceful fallback
    class _FallbackSettings:  # pylint: disable=too-few-public-methods
        ENABLE_SELF_TRAINING = True

    settings = _FallbackSettings()  # type: ignore[assignment]
    logging.getLogger(__name__).warning("Using fallback settings: %s", exc)

from ml.train_daily import MODEL_REGISTRY, TrainResult, train_model

logger = logging.getLogger(__name__)


def retrain_models() -> List[TrainResult]:
    """Run the self-training loop for all registered models."""

    if not getattr(settings, "ENABLE_SELF_TRAINING", True):
        logger.info("Self-training disabled via ENABLE_SELF_TRAINING flag")
        return []

    results: List[TrainResult] = []
    for model_name in sorted(MODEL_REGISTRY.keys()):
        result = train_model(model_name)
        results.append(result)
        if result.rolled_back:
            logger.warning(
                "Rolled back %s (drop=%.4f)",
                model_name,
                result.accuracy_drop or 0.0,
            )
        else:
            logger.info(
                "Model %s updated -> v%s (accuracy=%.4f)",
                model_name,
                result.new_version,
                result.accuracy,
            )
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    retrain_models()


if __name__ == "__main__":
    main()
