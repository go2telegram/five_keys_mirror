"""Epsilon-greedy multi-armed bandit utilities."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict


class BanditError(RuntimeError):
    """Raised when the bandit cannot operate (e.g. no arms)."""


@dataclass
class ArmStats:
    name: str
    shows: int = 0
    clicks: int = 0

    @property
    def ctr(self) -> float:
        if self.shows == 0:
            return 0.0
        return self.clicks / self.shows


@dataclass
class EpsilonGreedyBandit:
    epsilon: float = 0.1
    rng: random.Random = field(default_factory=random.Random)
    arms: Dict[str, ArmStats] = field(default_factory=dict)

    def ensure_arm(self, name: str) -> ArmStats:
        if name not in self.arms:
            self.arms[name] = ArmStats(name=name)
        return self.arms[name]

    def select(self) -> ArmStats:
        if not self.arms:
            raise BanditError("No arms registered")
        if self.rng.random() < self.epsilon:
            name = self.rng.choice(list(self.arms))
            return self.arms[name]
        return max(self.arms.values(), key=lambda arm: arm.ctr)

    def record(self, name: str, *, click: bool) -> ArmStats:
        arm = self.ensure_arm(name)
        arm.shows += 1
        if click:
            arm.clicks += 1
        return arm

    def to_dict(self) -> Dict[str, dict[str, float | int]]:
        return {
            name: {"shows": arm.shows, "clicks": arm.clicks, "ctr": arm.ctr}
            for name, arm in self.arms.items()
        }
