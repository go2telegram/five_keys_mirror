"""A/B experiment utilities with deterministic assignments."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping

import yaml

from app.content import CONTENT_ROOT

EXPERIMENTS_FILE = CONTENT_ROOT / "ab_experiments.yaml"


@dataclass(frozen=True)
class Variant:
    name: str
    weight: float
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Experiment:
    id: str
    variants: tuple[Variant, ...]
    conditions: Mapping[str, Any]


class AssignmentStorage:
    """Simple in-memory storage for experiment assignments."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get(self, experiment_id: str, subject_id: str) -> str | None:
        return self._store.get((experiment_id, subject_id))

    def set(self, experiment_id: str, subject_id: str, variant: str) -> None:
        self._store[(experiment_id, subject_id)] = variant


def _load_raw() -> Mapping[str, Any]:
    if not EXPERIMENTS_FILE.exists():
        return {}
    with EXPERIMENTS_FILE.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, Mapping):
        raise RuntimeError("ab_experiments.yaml must contain a mapping")
    return payload


@lru_cache(maxsize=1)
def load_experiments() -> Mapping[str, Experiment]:
    raw = _load_raw()
    experiments: dict[str, Experiment] = {}
    for exp_id, data in raw.get("experiments", raw).items():
        if not isinstance(exp_id, str):
            continue
        variants_data = data.get("variants") if isinstance(data, Mapping) else None
        if not isinstance(variants_data, Mapping):
            continue
        variants: list[Variant] = []
        for name, payload in variants_data.items():
            if not isinstance(name, str):
                continue
            if isinstance(payload, Mapping):
                weight = float(payload.get("weight", 1.0))
                variant_payload = payload
            else:
                weight = 1.0
                variant_payload = {"value": payload}
            if weight <= 0:
                continue
            variants.append(Variant(name=name, weight=weight, payload=variant_payload))
        if not variants:
            continue
        conditions = data.get("conditions") if isinstance(data, Mapping) else {}
        if not isinstance(conditions, Mapping):
            conditions = {}
        experiments[exp_id] = Experiment(
            id=exp_id,
            variants=tuple(variants),
            conditions=conditions,
        )
    return experiments


def _eligible(experiment: Experiment, context: Mapping[str, Any] | None) -> bool:
    if not experiment.conditions:
        return True
    if not context:
        return False
    for key, expected in experiment.conditions.items():
        actual = context.get(key)
        if isinstance(expected, Iterable) and not isinstance(expected, (str, bytes)):
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _pick_variant(experiment: Experiment, subject_id: str) -> Variant:
    seed = f"{experiment.id}:{subject_id}".encode("utf-8")
    digest = hashlib.sha1(seed).digest()
    value = int.from_bytes(digest[:8], "big") / float(1 << 64)
    total = sum(variant.weight for variant in experiment.variants)
    cumulative = 0.0
    for variant in experiment.variants:
        cumulative += variant.weight / total
        if value <= cumulative:
            return variant
    return experiment.variants[-1]


DEFAULT_STORAGE = AssignmentStorage()


def assign_variant(
    storage: AssignmentStorage | None,
    experiment_id: str,
    subject_id: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> Variant | None:
    experiments = load_experiments()
    experiment = experiments.get(experiment_id)
    if experiment is None:
        return None
    if not _eligible(experiment, context):
        return None
    store = storage or DEFAULT_STORAGE
    assigned = store.get(experiment_id, subject_id)
    if assigned:
        for variant in experiment.variants:
            if variant.name == assigned:
                return variant
    variant = _pick_variant(experiment, subject_id)
    store.set(experiment_id, subject_id, variant.name)
    return variant


def select_copy(
    storage: AssignmentStorage | None,
    experiment_id: str,
    subject_id: str,
    *,
    context: Mapping[str, Any] | None = None,
    default: str | None = None,
) -> str | None:
    variant = assign_variant(storage, experiment_id, subject_id, context=context)
    if variant is None:
        return default
    payload = variant.payload
    text = payload.get("text") or payload.get("value")
    if isinstance(text, str):
        return text
    return default
