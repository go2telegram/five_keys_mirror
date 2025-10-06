"""Core integration layer for human–machine symbiosis metrics.

The module exposes :class:`SymbiosisCore` – a coordinator that aggregates
human feedback, machine decisions and tonal signals into a single shared
context.  The resulting snapshot is used by bot commands and HTTP endpoints
(e.g. ``/symbiosis_status``) to report the balance of the collaboration.

The storage is intentionally in-memory and lightweight.  We keep a sliding
window (default – 1000 iterations) that matches the DoD requirement for the
symbiosis programme.  The window maintains aggregated counters so that the
status call is an ``O(1)`` operation.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp ``value`` into the ``[minimum, maximum]`` range."""
    return max(minimum, min(value, maximum))


@dataclass
class SymbiosisInteraction:
    """One iteration of the human–machine collaboration."""

    human_feedback: float
    machine_decision: float
    tonal_signal: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.human_feedback = _clamp(self.human_feedback, 0.0, 1.0)
        self.machine_decision = _clamp(self.machine_decision, 0.0, 1.0)
        self.tonal_signal = _clamp(self.tonal_signal, -1.0, 1.0)


class SymbiosisCore:
    """Integrates human and machine signals into a single score.

    ``record_iteration`` merges human feedback, machine decision quality and a
    tonal alignment signal.  Metrics are preserved inside a sliding window.
    The main exported KPI is the Human–Machine Interaction coefficient (HMI),
    designed to stay above ``0.75`` for healthy collaboration.
    """

    def __init__(self, window_size: int = 1000) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")

        self.window_size = window_size
        self._lock = asyncio.Lock()
        self._events: Deque[SymbiosisInteraction] = deque()
        self._human_sum = 0.0
        self._machine_sum = 0.0
        self._tone_sum = 0.0
        self._iterations = 0

    async def record_iteration(
        self,
        *,
        human_feedback: float,
        machine_decision: float,
        tonal_signal: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store a single interaction inside the sliding window."""

        interaction = SymbiosisInteraction(
            human_feedback=human_feedback,
            machine_decision=machine_decision,
            tonal_signal=tonal_signal,
            meta=meta or {},
        )

        async with self._lock:
            if len(self._events) == self.window_size:
                outdated = self._events.popleft()
                self._human_sum -= outdated.human_feedback
                self._machine_sum -= outdated.machine_decision
                self._tone_sum -= outdated.tonal_signal

            self._events.append(interaction)
            self._human_sum += interaction.human_feedback
            self._machine_sum += interaction.machine_decision
            self._tone_sum += interaction.tonal_signal
            self._iterations += 1

    async def merge_feedback(
        self,
        human_feedback: Optional[float] = None,
        machine_decision: Optional[float] = None,
        tonal_signal: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Merge partial updates into the latest iteration.

        The helper is useful when human, machine and tonal data arrive at
        different moments but belong to the same interaction step.  The latest
        stored iteration is updated in-place.
        """

        async with self._lock:
            if not self._events:
                interaction = SymbiosisInteraction(
                    human_feedback=human_feedback or 0.0,
                    machine_decision=machine_decision or 0.0,
                    tonal_signal=tonal_signal or 0.0,
                    meta=meta or {},
                )
                self._events.append(interaction)
                self._human_sum += interaction.human_feedback
                self._machine_sum += interaction.machine_decision
                self._tone_sum += interaction.tonal_signal
                self._iterations += 1
                return

            current = self._events.pop()
            self._human_sum -= current.human_feedback
            self._machine_sum -= current.machine_decision
            self._tone_sum -= current.tonal_signal

            if human_feedback is not None:
                current.human_feedback = _clamp(human_feedback, 0.0, 1.0)
            if machine_decision is not None:
                current.machine_decision = _clamp(machine_decision, 0.0, 1.0)
            if tonal_signal is not None:
                current.tonal_signal = _clamp(tonal_signal, -1.0, 1.0)
            if meta:
                current.meta.update(meta)

            self._events.append(current)
            self._human_sum += current.human_feedback
            self._machine_sum += current.machine_decision
            self._tone_sum += current.tonal_signal

    async def status(self) -> Dict[str, Any]:
        """Return a snapshot suitable for ``/symbiosis_status``."""

        async with self._lock:
            if not self._events:
                return {
                    "iterations": self._iterations,
                    "window_size": self.window_size,
                    "active_interactions": 0,
                    "human_contribution": 0.0,
                    "machine_contribution": 0.0,
                    "tonal_alignment": 0.0,
                    "balance": 0.5,
                    "mutual_understanding": 0.5,
                    "hmi": 0.0,
                }

            count = len(self._events)
            human_avg = self._human_sum / count
            machine_avg = self._machine_sum / count
            tone_avg = self._tone_sum / count

            total_influence = self._human_sum + self._machine_sum
            balance = 0.5 if total_influence == 0 else self._human_sum / total_influence

            balance_score = 1.0 - abs(balance - 0.5) * 2.0
            tone_score = (tone_avg + 1.0) / 2.0
            mutual_understanding = (balance_score * 0.6) + (tone_score * 0.4)

            hmi = (
                human_avg * 0.35
                + machine_avg * 0.35
                + mutual_understanding * 0.30
            )

            return {
                "iterations": self._iterations,
                "window_size": self.window_size,
                "active_interactions": count,
                "human_contribution": round(human_avg, 3),
                "machine_contribution": round(machine_avg, 3),
                "tonal_alignment": round(tone_score, 3),
                "balance": round(balance, 3),
                "mutual_understanding": round(mutual_understanding, 3),
                "hmi": round(_clamp(hmi, 0.0, 1.0), 3),
            }

    async def health_ok(self, threshold: float = 0.75) -> bool:
        """Return ``True`` when the HMI is above the ``threshold``."""

        current = await self.status()
        return current["hmi"] >= threshold

    async def simulate_positive_loop(
        self,
        iterations: int,
        human_feedback: float = 0.85,
        machine_decision: float = 0.84,
        tonal_signal: float = 0.6,
    ) -> Dict[str, Any]:
        """Helper used in tests to confirm HMI behaviour."""

        for _ in range(iterations):
            await self.record_iteration(
                human_feedback=human_feedback,
                machine_decision=machine_decision,
                tonal_signal=tonal_signal,
                meta={"source": "simulation"},
            )
        return await self.status()


symbiosis_engine = SymbiosisCore()
"""Singleton used by the bot, HTTP handlers and tests."""
