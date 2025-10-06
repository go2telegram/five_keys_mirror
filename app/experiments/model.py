from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


# --- Data classes ---------------------------------------------------------


def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)


@dataclass(slots=True)
class Experiment:
    id: int
    key: str
    name: str
    hypothesis: str
    metric: str
    status: str = "draft"  # draft -> running -> completed
    created_at: dt.datetime = field(default_factory=_utcnow)
    started_at: Optional[dt.datetime] = None
    stopped_at: Optional[dt.datetime] = None
    winner_variant_id: Optional[int] = None
    min_sample: int = 50
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Variant:
    id: int
    experiment_id: int
    code: str
    name: str
    weight: float = 1.0
    payload: Dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Assignment:
    id: int
    experiment_id: int
    variant_id: int
    user_id: int
    assigned_at: dt.datetime = field(default_factory=_utcnow)


@dataclass(slots=True)
class MetricEvent:
    id: int
    experiment_id: int
    variant_id: int
    user_id: int
    metric: str
    value: float
    created_at: dt.datetime = field(default_factory=_utcnow)


# --- "Tables" -------------------------------------------------------------

_experiment_seq = 1
_variant_seq = 1
_assignment_seq = 1
_metric_seq = 1

EXPERIMENTS: Dict[int, Experiment] = {}
VARIANTS: Dict[int, Variant] = {}
ASSIGNMENTS: Dict[int, Assignment] = {}
METRICS: Dict[int, MetricEvent] = {}

EXPERIMENT_INDEX: Dict[str, int] = {}


# --- CRUD helpers ---------------------------------------------------------

def next_experiment_id() -> int:
    global _experiment_seq
    eid = _experiment_seq
    _experiment_seq += 1
    return eid


def next_variant_id() -> int:
    global _variant_seq
    vid = _variant_seq
    _variant_seq += 1
    return vid


def next_assignment_id() -> int:
    global _assignment_seq
    aid = _assignment_seq
    _assignment_seq += 1
    return aid


def next_metric_id() -> int:
    global _metric_seq
    mid = _metric_seq
    _metric_seq += 1
    return mid


def add_experiment(experiment: Experiment) -> Experiment:
    EXPERIMENTS[experiment.id] = experiment
    EXPERIMENT_INDEX[experiment.key] = experiment.id
    return experiment


def add_variant(variant: Variant) -> Variant:
    VARIANTS[variant.id] = variant
    return variant


def add_assignment(assignment: Assignment) -> Assignment:
    ASSIGNMENTS[assignment.id] = assignment
    return assignment


def add_metric(event: MetricEvent) -> MetricEvent:
    METRICS[event.id] = event
    return event


# --- Query helpers --------------------------------------------------------

def iter_experiments() -> Iterable[Experiment]:
    return EXPERIMENTS.values()


def iter_variants(experiment_id: int) -> Iterable[Variant]:
    return (v for v in VARIANTS.values() if v.experiment_id == experiment_id)


def get_experiment_by_key(key: str) -> Optional[Experiment]:
    eid = EXPERIMENT_INDEX.get(key)
    if eid is None:
        return None
    return EXPERIMENTS.get(eid)


def get_experiment(experiment_id: int) -> Optional[Experiment]:
    return EXPERIMENTS.get(experiment_id)


def get_variant(variant_id: int) -> Optional[Variant]:
    return VARIANTS.get(variant_id)


def get_assignments(experiment_id: int) -> List[Assignment]:
    return [a for a in ASSIGNMENTS.values() if a.experiment_id == experiment_id]


def get_metrics(experiment_id: int, metric: Optional[str] = None) -> List[MetricEvent]:
    events = [m for m in METRICS.values() if m.experiment_id == experiment_id]
    if metric:
        events = [m for m in events if m.metric == metric]
    return events


# --- Mutations ------------------------------------------------------------

def reset_tables():
    """Utility for tests to clear state."""
    global _experiment_seq, _variant_seq, _assignment_seq, _metric_seq
    EXPERIMENTS.clear()
    VARIANTS.clear()
    ASSIGNMENTS.clear()
    METRICS.clear()
    EXPERIMENT_INDEX.clear()
    _experiment_seq = 1
    _variant_seq = 1
    _assignment_seq = 1
    _metric_seq = 1
