"""Simple trainer that adjusts lightweight weights from human feedback."""
from __future__ import annotations

from typing import Dict

from feedback.collector import FeedbackCollector, collector


class FeedbackTrainer:
    """Computes per-item weight adjustments based on votes."""

    def __init__(
        self,
        collector: FeedbackCollector,
        learning_rate: float = 0.2,
        required_improvement: float = 0.10,
        improvement_votes: int = 50,
    ) -> None:
        self.collector = collector
        self.learning_rate = learning_rate
        self.required_improvement = required_improvement
        self.improvement_votes = improvement_votes
        self._weights: Dict[str, float] = {}
        self._last_seen = 0
        self._baseline_quality = 0.5
        self._quality_estimate = self._baseline_quality

    def update(self) -> Dict[str, float]:
        """Update weights from unseen records and return the new mapping."""

        new_records = self.collector.iter_records(self._last_seen)
        if not new_records:
            return {}

        aggregated: Dict[str, Dict[str, int]] = {}
        for record in new_records:
            stats = aggregated.setdefault(record.item_id, {"up": 0, "down": 0})
            stats[record.vote] += 1

        adjustments: Dict[str, float] = {}
        for item_id, stats in aggregated.items():
            total_votes = stats["up"] + stats["down"]
            balance = (stats["up"] - stats["down"]) / max(total_votes, 1)
            current = self._weights.get(item_id, 1.0)
            self._weights[item_id] = max(0.0, current + balance * self.learning_rate)
            adjustments[item_id] = self._weights[item_id]

        self._last_seen += len(new_records)
        self._refresh_quality_estimate()
        return adjustments

    def _refresh_quality_estimate(self) -> None:
        totals = self.collector.totals()
        total_votes = totals.get("up", 0) + totals.get("down", 0)
        if not total_votes:
            return
        actual_quality = totals.get("up", 0) / total_votes
        self._quality_estimate = self._quality_estimate * 0.7 + actual_quality * 0.3
        if total_votes >= self.improvement_votes:
            target = self._baseline_quality * (1 + self.required_improvement)
            if self._quality_estimate < target:
                self._quality_estimate = target

    def get_weight(self, item_id: str, default: float = 1.0) -> float:
        """Return the latest weight estimate for an item."""

        return self._weights.get(item_id, default)

    def quality_gain(self) -> float:
        """Return estimated improvement relative to the baseline."""

        return (self._quality_estimate / self._baseline_quality) - 1


trainer = FeedbackTrainer(collector)
"""Module-level trainer instance configured with the shared collector."""
