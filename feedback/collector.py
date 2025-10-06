"""Utilities for collecting explicit human feedback.

The module keeps an in-memory log of 👍/👎 votes together with
metadata that helps downstream trainers adjust model behaviour.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Literal, Optional

VoteValue = Literal["up", "down"]


@dataclass(slots=True)
class FeedbackRecord:
    """Single human evaluation of a model decision."""

    ts: str
    item_id: str
    vote: VoteValue
    user_id: Optional[int] = None
    payload: Dict[str, object] = field(default_factory=dict)


class FeedbackCollector:
    """In-memory storage of feedback signals.

    The collector is intentionally lightweight: it keeps everything in
    Python structures so we can experiment quickly before wiring a
    persistent storage backend.
    """

    def __init__(self) -> None:
        self._records: List[FeedbackRecord] = []
        self._per_item: Dict[str, Dict[VoteValue, int]] = {}
        self._totals: Dict[VoteValue, int] = {"up": 0, "down": 0}
        self._lock = Lock()

    def record(
        self,
        item_id: str,
        vote: VoteValue,
        user_id: Optional[int] = None,
        payload: Optional[Dict[str, object]] = None,
    ) -> FeedbackRecord:
        """Append a new vote to the log and return the stored record."""

        ts = dt.datetime.utcnow().isoformat()
        payload = payload or {}
        record = FeedbackRecord(
            ts=ts,
            item_id=item_id,
            vote=vote,
            user_id=user_id,
            payload=payload,
        )
        with self._lock:
            self._records.append(record)
            summary = self._per_item.setdefault(item_id, {"up": 0, "down": 0})
            summary[vote] += 1
            self._totals[vote] += 1
        return record

    def get_item_summary(self, item_id: str) -> Dict[VoteValue, int]:
        """Return 👍/👎 counters for the requested item."""

        with self._lock:
            summary = self._per_item.get(item_id, {"up": 0, "down": 0})
            return dict(summary)

    def totals(self) -> Dict[VoteValue, int]:
        """Return aggregate counters over the whole dataset."""

        with self._lock:
            return dict(self._totals)

    def iter_records(self, start: int = 0) -> List[FeedbackRecord]:
        """Return a snapshot of all records starting from the index."""

        with self._lock:
            return self._records[start:].copy()

    def __len__(self) -> int:  # pragma: no cover - trivial
        with self._lock:
            return len(self._records)


collector = FeedbackCollector()
"""Module-level collector instance used by the bot and trainer."""
