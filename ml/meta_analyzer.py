"""Meta-learning analyzer for selecting the most suitable algorithm."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jobs.meta_eval import run_evaluation


LOG_PATH = Path("ml/meta_analyzer.log")
STATE_PATH = Path("ml/meta_analyzer_state.json")
WEIGHTS = {
    "auc": 0.5,
    "mae": 0.3,
    "samples_per_second": 0.2,
}
IMPROVEMENT_THRESHOLD = 0.03


@dataclass(frozen=True)
class RankedAlgorithm:
    name: str
    score: float
    metrics: Dict[str, float]


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger("meta_analyzer")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def _normalize(values: Dict[str, float], higher_is_better: bool) -> Dict[str, float]:
    minimum = min(values.values())
    maximum = max(values.values())
    if abs(maximum - minimum) < 1e-12:
        default = 1.0 if higher_is_better else 0.0
        return {key: default for key in values}

    normalized = {}
    for key, value in values.items():
        if higher_is_better:
            normalized[key] = (value - minimum) / (maximum - minimum)
        else:
            normalized[key] = (maximum - value) / (maximum - minimum)
    return normalized


def _rank_algorithms(results: Dict[str, Dict[str, float]]) -> Dict[str, RankedAlgorithm]:
    auc_scores = {name: metrics["auc"] for name, metrics in results.items()}
    mae_scores = {name: metrics["mae"] for name, metrics in results.items()}
    speed_scores = {name: metrics["samples_per_second"] for name, metrics in results.items()}

    norm_auc = _normalize(auc_scores, higher_is_better=True)
    norm_mae = _normalize(mae_scores, higher_is_better=False)
    norm_speed = _normalize(speed_scores, higher_is_better=True)

    ranking: Dict[str, RankedAlgorithm] = {}
    for name in results:
        score = (
            norm_auc[name] * WEIGHTS["auc"]
            + norm_mae[name] * WEIGHTS["mae"]
            + norm_speed[name] * WEIGHTS["samples_per_second"]
        )
        ranking[name] = RankedAlgorithm(name=name, score=score, metrics=results[name])
    return ranking


def _load_state() -> Dict[str, Dict[str, float]]:
    if STATE_PATH.exists():
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def _save_state(state: Dict[str, Dict[str, float]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def _format_summary(ranking: Dict[str, RankedAlgorithm]) -> str:
    header = f"{'Algorithm':<18}{'Score':>8}{'AUC':>10}{'MAE':>10}{'Speed':>10}"
    lines = [header, "-" * len(header)]
    for algo in sorted(ranking.values(), key=lambda a: a.score, reverse=True):
        metrics = algo.metrics
        lines.append(
            f"{algo.name:<18}{algo.score:>8.3f}{metrics['auc']:>10.3f}{metrics['mae']:>10.3f}{metrics['samples_per_second']:>10.0f}"
        )
    return "\n".join(lines)


def analyze() -> Tuple[RankedAlgorithm, Dict[str, RankedAlgorithm]]:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = _configure_logger()

    results = run_evaluation()
    ranking = _rank_algorithms(results)
    best = max(ranking.values(), key=lambda item: item.score)

    state = _load_state()
    current = state.get("selected_algorithm")
    current_metrics = state.get("metrics", {})
    current_auc = current_metrics.get("auc", 0.0)

    improvement = None
    if current_auc:
        improvement = (best.metrics["auc"] - current_auc) / current_auc
    elif current is not None:
        improvement = 0.0

    logger.info("Meta-analysis completed. Best=%s score=%.3f", best.name, best.score)

    switched = False
    meets_threshold = improvement is None or improvement > IMPROVEMENT_THRESHOLD
    if current is None or (best.name != current and meets_threshold):
        previous = current or "<none>"
        switched = True
        improvement_str = "n/a" if improvement is None else f"{improvement * 100:.2f}%"
        logger.info(
            "Switching algorithm from %s to %s (AUC %.3f -> %.3f, +%s)",
            previous,
            best.name,
            current_auc,
            best.metrics["auc"],
            improvement_str,
        )
        state = {
            "selected_algorithm": best.name,
            "metrics": best.metrics,
        }
        _save_state(state)
    else:
        improvement_value = (improvement or 0.0) * 100
        logger.info(
            "Keeping algorithm %s (AUC %.3f). Improvement %.2f%%",
            current,
            current_auc,
            improvement_value,
        )

    summary = _format_summary(ranking)
    print(summary)
    if switched:
        if improvement is None:
            gain_msg = "AUC gain n/a (initial selection)"
        else:
            gain_msg = f"AUC gain {improvement * 100:.2f}%"
        print(f"\nAlgorithm updated to '{best.name}' ({gain_msg}).")
    else:
        print("\nNo update applied.")

    return best, ranking


if __name__ == "__main__":
    analyze()
