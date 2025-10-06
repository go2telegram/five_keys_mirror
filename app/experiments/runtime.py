from __future__ import annotations

import datetime as dt
import math
from random import random
from typing import Dict, List, Optional, Tuple

from .model import (
    Assignment,
    Experiment,
    MetricEvent,
    Variant,
    add_assignment,
    add_experiment,
    add_metric,
    add_variant,
    get_assignments,
    get_experiment_by_key,
    get_metrics,
    get_variant,
    iter_experiments,
    iter_variants,
    next_assignment_id,
    next_experiment_id,
    next_metric_id,
    next_variant_id,
)


# --- Experiment catalogue -------------------------------------------------

EXPERIMENT_TEMPLATES: Dict[str, Dict[str, object]] = {
    "welcome_text": {
        "name": "Приветствие — текст кнопки",
        "hypothesis": "Если добавить конкретику в приветствии, больше людей начнут квиз",
        "metric": "quiz_start",
        "min_sample": 80,
        "metadata": {
            "baseline_conversion": 0.11,
        },
        "variants": [
            {
                "code": "A",
                "name": "Контроль",
                "payload": {"text": "Начать путь к энергии"},
                "weight": 1.0,
            },
            {
                "code": "B",
                "name": "Промо-бонус",
                "payload": {"text": "Получить бесплатный чек-лист"},
                "weight": 1.0,
            },
        ],
    },
}

LOW_CONVERSION_THRESHOLD = 0.2
MIN_RUNTIME_MINUTES = 30  # избегаем мгновенных остановок


def _ensure_seed_data() -> None:
    for key, template in EXPERIMENT_TEMPLATES.items():
        if get_experiment_by_key(key):
            continue
        experiment = Experiment(
            id=next_experiment_id(),
            key=key,
            name=str(template["name"]),
            hypothesis=str(template["hypothesis"]),
            metric=str(template["metric"]),
            min_sample=int(template.get("min_sample", 50)),
            metadata=dict(template.get("metadata", {})),
        )
        add_experiment(experiment)
        for variant_tpl in template["variants"]:
            variant = Variant(
                id=next_variant_id(),
                experiment_id=experiment.id,
                code=str(variant_tpl.get("code", "")),
                name=str(variant_tpl.get("name", "")),
                weight=float(variant_tpl.get("weight", 1.0)),
                payload=dict(variant_tpl.get("payload", {})),
            )
            add_variant(variant)


_ensure_seed_data()


# --- Assignment helpers ---------------------------------------------------

def _pick_variant(variants: List[Variant]) -> Variant:
    # Простая взвешенная рулетка (псевдослучайное распределение)
    total = sum(max(v.weight, 0.0) for v in variants)
    if total <= 0:
        return variants[0]
    r = random() * total
    upto = 0.0
    for variant in variants:
        w = max(variant.weight, 0.0)
        upto += w
        if r <= upto:
            return variant
    return variants[-1]


def assign_user(user_id: int, experiment_key: str) -> Optional[Variant]:
    experiment = get_experiment_by_key(experiment_key)
    if not experiment or experiment.status != "running":
        return None

    variants = list(iter_variants(experiment.id))
    if not variants:
        return None

    # Проверяем существующее назначение
    for assignment in get_assignments(experiment.id):
        if assignment.user_id == user_id:
            return get_variant(assignment.variant_id)

    variant = _pick_variant(variants)
    add_assignment(
        Assignment(
            id=next_assignment_id(),
            experiment_id=experiment.id,
            variant_id=variant.id,
            user_id=user_id,
        )
    )
    return variant


# --- Tracking -------------------------------------------------------------

def track_metric(user_id: int, experiment_key: str, metric: str, value: float) -> None:
    experiment = get_experiment_by_key(experiment_key)
    if not experiment or experiment.status != "running":
        return

    variant = None
    for assignment in get_assignments(experiment.id):
        if assignment.user_id == user_id:
            variant = get_variant(assignment.variant_id)
            break

    if not variant:
        variant = assign_user(user_id, experiment_key)
    if not variant:
        return

    add_metric(
        MetricEvent(
            id=next_metric_id(),
            experiment_id=experiment.id,
            variant_id=variant.id,
            user_id=user_id,
            metric=metric,
            value=float(value),
        )
    )


# --- Analytics ------------------------------------------------------------

def _variant_sample(experiment_id: int, variant_id: int, metric: str) -> Tuple[int, float]:
    assignments = [a for a in get_assignments(experiment_id) if a.variant_id == variant_id]
    metrics = [m for m in get_metrics(experiment_id, metric) if m.variant_id == variant_id]
    n = len(assignments)
    success = sum(1.0 for m in metrics if m.value > 0)
    return n, success


def _two_proportion_pvalue(success_a: float, n_a: int, success_b: float, n_b: int) -> float:
    if n_a == 0 or n_b == 0:
        return 1.0
    p1 = success_a / n_a
    p2 = success_b / n_b
    pooled = (success_a + success_b) / (n_a + n_b)
    var = pooled * (1 - pooled) * ((1 / n_a) + (1 / n_b))
    if var <= 0:
        return 1.0
    z = (p2 - p1) / math.sqrt(var)
    # двусторонний тест
    tail = 0.5 * math.erfc(abs(z) / math.sqrt(2))
    return min(1.0, 2 * tail)


def _bonferroni(p_value: float, m: int) -> float:
    if m <= 1:
        return p_value
    return min(1.0, p_value * m)


def analyze_experiment(experiment: Experiment, total_tests: int) -> Optional[Dict[str, object]]:
    variants = list(iter_variants(experiment.id))
    if len(variants) < 2:
        return None

    metric = experiment.metric
    baseline = variants[0]
    challenger = variants[1]

    n_a, s_a = _variant_sample(experiment.id, baseline.id, metric)
    n_b, s_b = _variant_sample(experiment.id, challenger.id, metric)

    if n_a < experiment.min_sample or n_b < experiment.min_sample:
        return None

    if experiment.started_at:
        elapsed = (
            dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc) - experiment.started_at
        ).total_seconds() / 60
        if elapsed < MIN_RUNTIME_MINUTES:
            return None

    rate_a = (s_a / n_a) if n_a else 0.0
    rate_b = (s_b / n_b) if n_b else 0.0
    lift = rate_b - rate_a
    rel_lift = (lift / rate_a * 100) if rate_a > 0 else (rate_b * 100)
    p_value = _two_proportion_pvalue(s_a, n_a, s_b, n_b)
    p_corrected = _bonferroni(p_value, total_tests)

    return {
        "baseline": {
            "variant": baseline,
            "assignments": n_a,
            "success": s_a,
            "rate": rate_a,
        },
        "challenger": {
            "variant": challenger,
            "assignments": n_b,
            "success": s_b,
            "rate": rate_b,
        },
        "lift_abs": lift,
        "lift_rel": rel_lift,
        "p_value": p_value,
        "p_corrected": p_corrected,
    }


# --- Lifecycle ------------------------------------------------------------

def start_experiment(experiment: Experiment) -> Experiment:
    if experiment.status == "running":
        return experiment
    experiment.status = "running"
    experiment.started_at = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    return experiment


def complete_experiment(experiment: Experiment, winner: Optional[Variant]) -> Experiment:
    experiment.status = "completed"
    experiment.stopped_at = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    experiment.winner_variant_id = winner.id if winner else None
    return experiment


def pick_next_experiment() -> Optional[Experiment]:
    candidates: List[Experiment] = []
    for experiment in iter_experiments():
        if experiment.status != "draft":
            continue
        baseline_conv = float(experiment.metadata.get("baseline_conversion", 0.0))
        if baseline_conv <= LOW_CONVERSION_THRESHOLD:
            candidates.append(experiment)
    if not candidates:
        return None
    candidates.sort(key=lambda e: float(e.metadata.get("baseline_conversion", 0.0)))
    return candidates[0]


def get_running_experiments() -> List[Experiment]:
    return [exp for exp in iter_experiments() if exp.status == "running"]


def ensure_next_experiment_started() -> Optional[Experiment]:
    running = get_running_experiments()
    if running:
        return None
    next_exp = pick_next_experiment()
    if not next_exp:
        return None
    start_experiment(next_exp)
    return next_exp


def evaluate_running_experiments(total_tests: int) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    for experiment in get_running_experiments():
        analysis = analyze_experiment(experiment, total_tests)
        if not analysis:
            continue
        if analysis.get("p_corrected", 1.0) > 0.05:
            continue
        if analysis["lift_abs"] > 0:
            winner = analysis["challenger"]["variant"]
            winner_lift = analysis["lift_rel"]
        else:
            winner = analysis["baseline"]["variant"]
            winner_lift = abs(analysis["lift_rel"])
        complete_experiment(experiment, winner)
        analysis["experiment"] = experiment
        analysis["winner"] = winner
        analysis["winner_lift"] = winner_lift
        results.append(analysis)
    return results


def get_active_experiments() -> List[Experiment]:
    return get_running_experiments()


def get_experiment_status(experiment: Experiment) -> Dict[str, object]:
    variants = list(iter_variants(experiment.id))
    stats = []
    for variant in variants:
        assignments = [a for a in get_assignments(experiment.id) if a.variant_id == variant.id]
        metrics = [m for m in get_metrics(experiment.id, experiment.metric) if m.variant_id == variant.id]
        conversions = sum(1 for m in metrics if m.value > 0)
        rate = (conversions / len(assignments)) if assignments else 0.0
        stats.append(
            {
                "variant": variant,
                "assignments": len(assignments),
                "conversions": conversions,
                "rate": rate,
            }
        )
    return {
        "experiment": experiment,
        "stats": stats,
    }
