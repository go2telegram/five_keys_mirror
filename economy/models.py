"""Domain models for the internal token economy layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional
from collections import deque


@dataclass(slots=True)
class Transaction:
    """Represents a single wallet operation."""

    id: str
    ts: datetime
    kind: str
    amount: int
    actor_id: int
    counterparty_id: Optional[int] = None
    note: str = ""


@dataclass(slots=True)
class Wallet:
    """Aggregated snapshot of a participant wallet."""

    user_id: int
    balance: int = 0
    level: str = "Новичок"
    tokens_earned: int = 0
    tokens_spent: int = 0
    history: Deque[Transaction] = field(default_factory=lambda: deque(maxlen=50))

    def record(self, tx: Transaction) -> None:
        """Add transaction to the head of the personal ledger."""
        self.history.appendleft(tx)
