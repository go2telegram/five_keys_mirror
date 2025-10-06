"""Offline evaluation job for candidate learning algorithms.

This module synthesizes a small dataset and computes evaluation metrics
for several algorithms. The results are returned as a dictionary and may
optionally be persisted to JSON so the meta analyzer can read them.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


DATASET_SEED = 903
DEFAULT_OUTPUT_PATH = Path("ml/meta_eval_results.json")


@dataclass(frozen=True)
class EvaluationResult:
    """Container for model evaluation metrics."""

    auc: float
    mae: float
    samples_per_second: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "auc": self.auc,
            "mae": self.mae,
            "samples_per_second": self.samples_per_second,
        }


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _generate_dataset(n_samples: int = 240) -> Sequence[Dict[str, float]]:
    """Create a synthetic binary classification dataset.

    The dataset is deterministic thanks to the global seed.
    Each sample contains two features and a binary label.
    """

    random.seed(DATASET_SEED)
    dataset = []
    for i in range(n_samples):
        feature_a = random.gauss(0.0, 1.0)
        feature_b = random.gauss(0.0, 1.5)
        linear_term = 0.9 * feature_a - 0.4 * feature_b + 0.1 * i / n_samples
        probability = _sigmoid(linear_term)
        label = 1 if random.random() < probability else 0
        dataset.append({
            "f_a": feature_a,
            "f_b": feature_b,
            "label": label,
        })
    return dataset


def _rank_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Compute the ROC AUC using the rank statistic (Mann-Whitney U)."""

    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5

    paired = sorted(zip(y_score, y_true))
    rank = 1
    pos_rank_sum = 0.0
    # Simple ranking without ties (scores are unique because of the offsets).
    for _score, label in paired:
        if label == 1:
            pos_rank_sum += rank
        rank += 1

    auc = (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return max(0.0, min(1.0, auc))


def _mean_absolute_error(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    total = 0.0
    for y_t, y_p in zip(y_true, y_pred):
        total += abs(y_t - y_p)
    return total / len(y_true)


def _simulate_algorithm_scores(
    dataset: Sequence[Dict[str, float]],
    weight_a: float,
    weight_b: float,
    bias: float,
    noise_scale: float,
) -> List[float]:
    """Generate prediction scores for a candidate algorithm."""

    random.seed(int((weight_a + weight_b + bias) * 1_000))
    outputs = []
    for index, sample in enumerate(dataset):
        linear_combination = (
            weight_a * sample["f_a"]
            + weight_b * sample["f_b"]
            + bias
            + math.sin(index * 0.17) * noise_scale
        )
        # Offset by index to avoid identical scores which would complicate ranking.
        outputs.append(_sigmoid(linear_combination + index * 1e-6))
    return outputs


ALGORITHMS = {
    "baseline": {
        "weights": (0.8, -0.9, 0.02),
        "noise": 0.18,
        "speed": 2_400,
    },
    "meta_forest": {
        "weights": (1.05, -0.5, 0.05),
        "noise": 0.06,
        "speed": 2_050,
    },
    "adaptive_boost": {
        "weights": (1.35, -0.45, 0.04),
        "noise": 0.01,
        "speed": 1_980,
    },
}


def evaluate_algorithms() -> Dict[str, EvaluationResult]:
    """Evaluate every algorithm on a common dataset."""

    dataset = _generate_dataset()
    labels = [row["label"] for row in dataset]
    results: Dict[str, EvaluationResult] = {}

    for name, params in ALGORITHMS.items():
        weight_a, weight_b, bias = params["weights"]
        predictions = _simulate_algorithm_scores(
            dataset,
            weight_a=weight_a,
            weight_b=weight_b,
            bias=bias,
            noise_scale=params["noise"],
        )
        auc = _rank_auc(labels, predictions)
        mae = _mean_absolute_error(labels, predictions)
        samples_per_second = params["speed"]
        results[name] = EvaluationResult(
            auc=auc,
            mae=mae,
            samples_per_second=samples_per_second,
        )
    return results


def run_evaluation(output_path: Path | None = DEFAULT_OUTPUT_PATH) -> Dict[str, Dict[str, float]]:
    """Run the evaluation and optionally persist the JSON payload."""

    results = evaluate_algorithms()
    payload = {name: result.to_dict() for name, result in results.items()}

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    return payload


if __name__ == "__main__":
    run_evaluation()
