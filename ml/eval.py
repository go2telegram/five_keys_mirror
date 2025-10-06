"""Utility script to compare two persisted model artefacts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ml.train_daily import (
    MODEL_REGISTRY,
    artifact_to_model,
    evaluate_model,
    load_artifact,
    prepare_training_data,
)

logger = logging.getLogger(__name__)


def _infer_model_name(path: Path) -> str:
    stem = path.stem
    if "_v" not in stem:
        raise ValueError(f"Cannot infer model name from {path}")
    return stem.split("_v", 1)[0]


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two model pickles on a shared dataset")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("OLD", "NEW"),
        required=True,
        help="Paths to model artefacts",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce log verbosity",
    )
    return parser.parse_args(argv)


def _accuracy(model_path: Path, model_name: str, X_test, y_test) -> float:
    artifact = load_artifact(model_path)
    if tuple(MODEL_REGISTRY[model_name].features) != artifact.features:
        raise ValueError("Feature mismatch between artefact and registry")
    model, scaler = artifact_to_model(artifact)
    return float(evaluate_model(model, scaler, X_test, y_test))


def main(argv: Iterable[str] | None = None) -> dict[str, float]:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO)

    old_path = Path(args.compare[0])
    new_path = Path(args.compare[1])

    if not old_path.exists() or not new_path.exists():
        raise FileNotFoundError("Both model artefacts must exist")

    model_name = _infer_model_name(old_path)
    if model_name != _infer_model_name(new_path):
        raise ValueError("Models belong to different registries")
    if model_name not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model {model_name}")

    _, X_test, _, y_test = prepare_training_data(model_name)
    old_acc = _accuracy(old_path, model_name, X_test, y_test)
    new_acc = _accuracy(new_path, model_name, X_test, y_test)
    diff = new_acc - old_acc

    payload = {
        "model": model_name,
        "old_accuracy": round(old_acc, 4),
        "new_accuracy": round(new_acc, 4),
        "delta": round(diff, 4),
    }
    logger.info("Comparison %s -> Δ %.4f", model_name, diff)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    main()
