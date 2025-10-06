"""Trust and reputation management for distributed agents.

This module keeps an in-memory table of trust scores with exponential decay.
The logic is intentionally stateful because the rest of the project stores
runtime data in memory as well (see :mod:`app.storage`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean, pstdev
from threading import RLock
from typing import Dict, List, Tuple

from app.config import settings


@dataclass
class TrustScore:
    """Internal representation of an agent trust score."""

    agent_id: str
    positive: float = 1.0
    negative: float = 1.0
    decay_rate: float = 0.05
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def apply_decay(self, now: datetime | None = None) -> None:
        """Apply exponential decay to the accumulated evidence."""

        if now is None:
            now = datetime.now(timezone.utc)

        if now <= self.updated_at:
            return

        elapsed_hours = (now - self.updated_at).total_seconds() / 3600
        if elapsed_hours <= 0:
            return

        factor = math.exp(-self.decay_rate * elapsed_hours)
        self.positive *= factor
        self.negative *= factor
        self.updated_at = now

    @property
    def score(self) -> float:
        total = self.positive + self.negative
        if total == 0:
            return 0.5
        # Beta(1, 1) prior keeps the score away from hard 0/1 boundaries.
        return (self.positive + 1.0) / (total + 2.0)

    def register_observation(self, outcome: float, weight: float = 1.0) -> None:
        outcome = max(0.0, min(1.0, outcome))
        weight = max(0.0, weight)
        if weight == 0:
            return
        self.positive += outcome * weight
        self.negative += (1.0 - outcome) * weight


class TrustRegistry:
    """Container that keeps trust scores for every known agent."""

    def __init__(self, default_decay: float = 0.05):
        self._scores: Dict[str, TrustScore] = {}
        self._default_decay = default_decay
        self._lock = RLock()

    def _get_or_create(self, agent_id: str, decay_rate: float | None = None) -> TrustScore:
        with self._lock:
            if agent_id not in self._scores:
                self._scores[agent_id] = TrustScore(
                    agent_id=agent_id,
                    decay_rate=decay_rate if decay_rate is not None else self._default_decay,
                )
            record = self._scores[agent_id]
            if decay_rate is not None:
                record.decay_rate = decay_rate
            record.apply_decay()
            return record

    def record(self, agent_id: str, outcome: float, *, weight: float = 1.0, decay_rate: float | None = None) -> float:
        record = self._get_or_create(agent_id, decay_rate)
        record.register_observation(outcome, weight)
        return record.score

    def bulk_decay(self, now: datetime | None = None) -> None:
        with self._lock:
            for record in self._scores.values():
                record.apply_decay(now)

    def get_score(self, agent_id: str) -> float:
        record = self._scores.get(agent_id)
        if record is None:
            return 0.5
        record.apply_decay()
        return record.score

    def distribution(self) -> List[Tuple[str, float]]:
        records = list(self._scores.values())
        for record in records:
            record.apply_decay()
        return sorted(((r.agent_id, r.score) for r in records), key=lambda item: item[1], reverse=True)

    def metrics(self) -> Dict[str, float]:
        records = list(self._scores.values())
        if not records:
            return {"avg_trust": 0.0, "trust_deviation": 0.0}
        scores = [record.score for record in records]
        avg = mean(scores)
        deviation = pstdev(scores) if len(scores) > 1 else 0.0
        return {"avg_trust": avg, "trust_deviation": deviation}

    def snapshot(self) -> List[TrustScore]:
        records = list(self._scores.values())
        for record in records:
            record.apply_decay()
        return records

    def reset(self) -> None:
        with self._lock:
            self._scores.clear()


TRUST_REGISTRY = TrustRegistry()


def _trust_enabled() -> bool:
    return getattr(settings, "ENABLE_TRUST_SYSTEM", True)


def record_agent_interaction(agent_id: str, outcome: float, *, weight: float = 1.0, decay_rate: float | None = None) -> float:
    if not _trust_enabled():
        return 0.5
    return TRUST_REGISTRY.record(agent_id, outcome, weight=weight, decay_rate=decay_rate)


def record_success(agent_id: str, weight: float = 1.0, *, decay_rate: float | None = None) -> float:
    return record_agent_interaction(agent_id, 1.0, weight=weight, decay_rate=decay_rate)


def record_failure(agent_id: str, weight: float = 1.0, *, decay_rate: float | None = None) -> float:
    return record_agent_interaction(agent_id, 0.0, weight=weight, decay_rate=decay_rate)


def get_trust_score(agent_id: str) -> float:
    if not _trust_enabled():
        return 0.5
    return TRUST_REGISTRY.get_score(agent_id)


def get_trust_distribution() -> List[Tuple[str, float]]:
    if not _trust_enabled():
        return []
    return TRUST_REGISTRY.distribution()


def get_trust_metrics() -> Dict[str, float]:
    if not _trust_enabled():
        return {"avg_trust": 0.0, "trust_deviation": 0.0}
    return TRUST_REGISTRY.metrics()


def reset_trust() -> None:
    TRUST_REGISTRY.reset()
