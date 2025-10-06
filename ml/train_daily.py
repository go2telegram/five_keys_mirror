"""Daily retraining entry point without heavy external deps."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import os
import pickle
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import joblib
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    class _PickleJoblib:
        @staticmethod
        def dump(obj, path):
            with Path(path).open("wb") as fh:
                pickle.dump(obj, fh)

        @staticmethod
        def load(path):
            with Path(path).open("rb") as fh:
                return pickle.load(fh)

    joblib = _PickleJoblib()

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.metrics import update_model_metric

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "artifacts/models"))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
ROLLBACK_THRESHOLD = 0.05
DEFAULT_TEST_SIZE = 0.2
RANDOM_STATE = 42


@dataclass(frozen=True)
class ModelConfig:
    name: str
    target: str
    features: Tuple[str, ...]
    dataset: Optional[str] = None
    rollback_threshold: float = ROLLBACK_THRESHOLD


MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "recommendations": ModelConfig(
        name="recommendations",
        target="purchased",
        features=(
            "user_tenure_days",
            "session_count",
            "category_affinity",
            "price_sensitivity",
        ),
    ),
    "segments": ModelConfig(
        name="segments",
        target="is_high_value",
        features=(
            "avg_ticket",
            "visits_per_month",
            "support_calls",
            "loyalty_score",
        ),
    ),
    "ctr": ModelConfig(
        name="ctr",
        target="clicked",
        features=(
            "impressions_7d",
            "historical_ctr",
            "creative_quality",
            "hour_of_day",
        ),
    ),
}


@dataclass
class TrainResult:
    model_name: str
    accuracy: float
    new_version: Optional[int]
    model_path: Optional[Path]
    rolled_back: bool
    prev_version: Optional[int] = None
    prev_accuracy: Optional[float] = None
    accuracy_drop: Optional[float] = None
    metadata: Dict[str, object] | None = None


@dataclass
class ModelArtifact:
    weights: List[float]
    bias: float
    means: List[float]
    stds: List[float]
    features: Tuple[str, ...]


class StandardScaler:
    def __init__(self) -> None:
        self.means: List[float] = []
        self.stds: List[float] = []

    def fit(self, X: Sequence[Sequence[float]]) -> "StandardScaler":
        if not X:
            raise ValueError("Cannot fit scaler on empty dataset")
        feature_count = len(X[0])
        self.means = []
        self.stds = []
        for idx in range(feature_count):
            column = [row[idx] for row in X]
            mean = sum(column) / len(column)
            variance = sum((value - mean) ** 2 for value in column) / max(len(column) - 1, 1)
            std = math.sqrt(variance) or 1.0
            self.means.append(mean)
            self.stds.append(std)
        return self

    def transform(self, X: Sequence[Sequence[float]]) -> List[List[float]]:
        return [
            [
                (row[idx] - self.means[idx]) / self.stds[idx]
                if self.stds[idx]
                else row[idx] - self.means[idx]
                for idx in range(len(self.means))
            ]
            for row in X
        ]

    @classmethod
    def from_params(cls, means: Sequence[float], stds: Sequence[float]) -> "StandardScaler":
        scaler = cls()
        scaler.means = list(means)
        scaler.stds = [std if std else 1.0 for std in stds]
        return scaler


class LogisticModel:
    def __init__(self, n_features: int, learning_rate: float = 0.05, epochs: int = 150) -> None:
        self.weights = [0.0 for _ in range(n_features)]
        self.bias = 0.0
        self.learning_rate = learning_rate
        self.epochs = epochs

    @staticmethod
    def _sigmoid(z: float) -> float:
        z = max(min(z, 60.0), -60.0)
        return 1.0 / (1.0 + math.exp(-z))

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> None:
        for _ in range(self.epochs):
            for row, target in zip(X, y):
                z = self.bias + sum(w * value for w, value in zip(self.weights, row))
                pred = self._sigmoid(z)
                error = pred - target
                for idx in range(len(self.weights)):
                    self.weights[idx] -= self.learning_rate * error * row[idx]
                self.bias -= self.learning_rate * error

    def predict_proba(self, row: Sequence[float]) -> float:
        z = self.bias + sum(w * value for w, value in zip(self.weights, row))
        return self._sigmoid(z)

    def predict(self, row: Sequence[float]) -> int:
        return 1 if self.predict_proba(row) >= 0.5 else 0

    def predict_many(self, X: Sequence[Sequence[float]]) -> List[int]:
        return [self.predict(row) for row in X]


class DataLakeClient:
    def __init__(self, base_path: Path | str = Path("data_lake")) -> None:
        self.base_path = Path(base_path)

    def fetch(self, dataset_name: str) -> List[Dict[str, float]]:
        path = self.base_path / f"{dataset_name}.csv"
        if path.exists():
            return self._read_csv(path)
        return self._generate(dataset_name)

    def _read_csv(self, path: Path) -> List[Dict[str, float]]:
        import csv

        rows: List[Dict[str, float]] = []
        with path.open() as fh:
            reader = csv.DictReader(fh)
            for line in reader:
                row: Dict[str, float] = {}
                for key, value in line.items():
                    try:
                        row[key] = float(value)
                    except (TypeError, ValueError):
                        row[key] = 0.0
                rows.append(row)
        return rows

    def _generate(self, dataset_name: str) -> List[Dict[str, float]]:
        rng = random.Random(37 * sum(ord(ch) for ch in dataset_name))
        rows = 2000
        data: List[Dict[str, float]] = []

        if dataset_name == "recommendations":
            for _ in range(rows):
                tenure = rng.randint(1, 365)
                sessions = max(1, int(rng.gauss(6.0, 2.5)))
                affinity = rng.random()
                price = rng.random()
                score = 0.002 * tenure + 0.3 * affinity - 0.25 * price + 0.05 * sessions
                noise = rng.gauss(0, 0.4)
                purchased = 1 if score + noise > 0 else 0
                data.append(
                    {
                        "user_tenure_days": float(tenure),
                        "session_count": float(sessions),
                        "category_affinity": affinity,
                        "price_sensitivity": price,
                        "purchased": float(purchased),
                    }
                )
            return data

        if dataset_name == "segments":
            for _ in range(rows):
                avg_ticket = max(20.0, rng.gauss(120.0, 30.0))
                visits = max(0.0, rng.gauss(5.0, 2.0))
                support = max(0.0, rng.gauss(1.0, 0.8))
                loyalty = rng.uniform(0, 100)
                latent = 0.01 * avg_ticket + 0.4 * loyalty - 0.3 * support + 0.2 * visits
                noise = rng.gauss(0, 8.0)
                high_value = 1 if latent + noise > 45 else 0
                data.append(
                    {
                        "avg_ticket": avg_ticket,
                        "visits_per_month": visits,
                        "support_calls": support,
                        "loyalty_score": loyalty,
                        "is_high_value": float(high_value),
                    }
                )
            return data

        if dataset_name == "ctr":
            for _ in range(rows):
                impressions = rng.randint(100, 5000)
                historical_ctr = rng.random()
                creative_quality = min(1.0, max(0.0, rng.gauss(0.5, 0.15)))
                hour = rng.randint(0, 23)
                latent = -2 + 1.8 * historical_ctr + 0.9 * creative_quality + 0.02 * (12 - abs(hour - 12))
                noise = rng.gauss(0, 0.8)
                clicked = 1 if latent + noise > 0 else 0
                data.append(
                    {
                        "impressions_7d": float(impressions),
                        "historical_ctr": historical_ctr,
                        "creative_quality": creative_quality,
                        "hour_of_day": float(hour),
                        "clicked": float(clicked),
                    }
                )
            return data

        raise KeyError(f"Unsupported dataset '{dataset_name}'")


def prepare_training_data(
    model_name: str,
    data_client: DataLakeClient | None = None,
) -> tuple[List[List[float]], List[List[float]], List[int], List[int]]:
    if model_name not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model: {model_name}")

    cfg = MODEL_REGISTRY[model_name]
    dataset_name = cfg.dataset or cfg.name
    client = data_client or DataLakeClient()
    raw_rows = client.fetch(dataset_name)

    features = list(cfg.features)
    target = cfg.target

    X: List[List[float]] = []
    y: List[int] = []
    for row in raw_rows:
        if any(feature not in row for feature in features) or target not in row:
            continue
        X.append([float(row[feature]) for feature in features])
        y.append(int(row[target]))

    return _train_test_split(X, y, test_size=DEFAULT_TEST_SIZE, seed=RANDOM_STATE)


def _train_test_split(
    X: Sequence[Sequence[float]],
    y: Sequence[int],
    *,
    test_size: float,
    seed: int,
) -> tuple[List[List[float]], List[List[float]], List[int], List[int]]:
    if not X:
        raise ValueError("Empty dataset")

    rng = random.Random(seed)
    indices = list(range(len(X)))
    rng.shuffle(indices)
    cutoff = max(1, int(len(indices) * (1 - test_size)))
    cutoff = min(cutoff, len(indices) - 1)

    train_idx = indices[:cutoff]
    test_idx = indices[cutoff:]

    X_train = [list(X[i]) for i in train_idx]
    X_test = [list(X[i]) for i in test_idx]
    y_train = [int(y[i]) for i in train_idx]
    y_test = [int(y[i]) for i in test_idx]
    return X_train, X_test, y_train, y_test


def _discover_previous_model(model_name: str) -> tuple[Optional[int], Optional[Path]]:
    if not ARTIFACTS_DIR.exists():
        return None, None

    prefix = f"{model_name}_v"
    candidates: List[tuple[int, Path]] = []
    for path in ARTIFACTS_DIR.glob(f"{model_name}_v*.pkl"):
        stem = path.stem
        if not stem.startswith(prefix):
            continue
        try:
            version = int(stem.replace(prefix, ""))
        except ValueError:
            continue
        candidates.append((version, path))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[0])


def artifact_to_model(artifact: ModelArtifact) -> tuple[LogisticModel, StandardScaler]:
    model = LogisticModel(len(artifact.weights))
    model.weights = list(artifact.weights)
    model.bias = float(artifact.bias)
    scaler = StandardScaler.from_params(artifact.means, artifact.stds)
    return model, scaler


def evaluate_model(model: LogisticModel, scaler: StandardScaler, X: List[List[float]], y: List[int]) -> float:
    transformed = scaler.transform(X)
    predictions = model.predict_many(transformed)
    correct = sum(1 for pred, target in zip(predictions, y) if pred == target)
    return correct / len(y)


def load_artifact(path: Path) -> ModelArtifact:
    data = joblib.load(path)
    return ModelArtifact(
        weights=list(data["weights"]),
        bias=float(data["bias"]),
        means=list(data["means"]),
        stds=list(data["stds"]),
        features=tuple(data["features"]),
    )


def train_model(
    model_name: str,
    *,
    data_client: DataLakeClient | None = None,
    rollback_threshold: Optional[float] = None,
) -> TrainResult:
    if model_name not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model: {model_name}")

    cfg = MODEL_REGISTRY[model_name]
    threshold = rollback_threshold if rollback_threshold is not None else cfg.rollback_threshold

    X_train_raw, X_test_raw, y_train, y_test = prepare_training_data(
        model_name, data_client=data_client
    )

    scaler = StandardScaler().fit(X_train_raw)
    X_train = scaler.transform(X_train_raw)
    X_test = scaler.transform(X_test_raw)

    model = LogisticModel(len(cfg.features))
    model.fit(X_train, y_train)
    accuracy = evaluate_model(model, scaler, X_test_raw, y_test)

    prev_version, prev_path = _discover_previous_model(model_name)
    prev_accuracy: Optional[float] = None
    if prev_path is not None:
        try:
            artifact = load_artifact(prev_path)
            prev_model, prev_scaler = artifact_to_model(artifact)
            prev_accuracy = evaluate_model(prev_model, prev_scaler, X_test_raw, y_test)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to evaluate previous model %s: %s", prev_path, exc)

    accuracy_drop = None
    if prev_accuracy is not None:
        accuracy_drop = prev_accuracy - accuracy

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    if accuracy_drop is not None and accuracy_drop > threshold:
        metadata = {
            "status": "rolled_back",
            "last_checked": now_iso,
            "reason": f"accuracy drop {accuracy_drop:.3f} > {threshold:.3f}",
        }
        if prev_accuracy is not None:
            metadata["active_accuracy"] = round(prev_accuracy, 4)
        update_model_metric(model_name, prev_version or 0, prev_accuracy or 0.0, metadata)
        logger.warning(
            "Rollback triggered for %s: drop %.3f > %.3f",
            model_name,
            accuracy_drop,
            threshold,
        )
        return TrainResult(
            model_name=model_name,
            accuracy=accuracy,
            new_version=None,
            model_path=None,
            rolled_back=True,
            prev_version=prev_version,
            prev_accuracy=prev_accuracy,
            accuracy_drop=accuracy_drop,
            metadata=metadata,
        )

    next_version = (prev_version or 0) + 1
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACTS_DIR / f"{model_name}_v{next_version}.pkl"

    artifact = {
        "weights": model.weights,
        "bias": model.bias,
        "means": scaler.means,
        "stds": scaler.stds,
        "features": list(cfg.features),
    }
    joblib.dump(artifact, model_path)
    print(f"[saved] {model_path}")

    metadata = {
        "status": "active",
        "last_trained": now_iso,
    }
    if accuracy_drop is not None:
        metadata["accuracy_delta"] = round(-accuracy_drop, 4)

    update_model_metric(model_name, next_version, accuracy, metadata)
    logger.info("Model %s trained -> v%s (accuracy %.3f)", model_name, next_version, accuracy)

    return TrainResult(
        model_name=model_name,
        accuracy=accuracy,
        new_version=next_version,
        model_path=model_path,
        rolled_back=False,
        prev_version=prev_version,
        prev_accuracy=prev_accuracy,
        accuracy_drop=accuracy_drop,
        metadata=metadata,
    )


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily self-training entry point")
    parser.add_argument(
        "--model",
        required=True,
        choices=sorted(MODEL_REGISTRY.keys()),
        help="Model name to retrain",
    )
    parser.add_argument(
        "--rollback-threshold",
        type=float,
        default=None,
        help="Override the rollback threshold (fractional accuracy drop)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence info logs, only warnings/errors are emitted",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> TrainResult:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO)
    return train_model(args.model, rollback_threshold=args.rollback_threshold)


if __name__ == "__main__":
    result = main()
    status = "rolled back" if result.rolled_back else "ok"
    payload = dataclasses.asdict(result)
    payload["status"] = status
    print(json.dumps(payload, default=str, ensure_ascii=False, indent=2))
