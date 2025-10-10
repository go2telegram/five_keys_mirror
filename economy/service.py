"""Utilities for managing the in-bot token economy."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

from economy.models import Transaction, Wallet

# ---- Persistent in-memory tables -------------------------------------------------
# Wallet registry acts as the economy_wallets table substitute.
WALLETS: Dict[int, Wallet] = {}
LEDGER: List[Transaction] = []

METRICS = {
    "tokens_earned": 0,
    "tokens_spent": 0,
}

_LEVELS = [
    (0, "Новичок"),
    (100, "Резидент"),
    (500, "Партнёр"),
    (1000, "Лидер"),
]


def _next_tx_id() -> str:
    return uuid4().hex


def _resolve_level(balance: int) -> str:
    level = _LEVELS[0][1]
    for threshold, name in _LEVELS:
        if balance >= threshold:
            level = name
        else:
            break
    return level


def get_wallet(user_id: int) -> Wallet:
    """Return wallet, creating an empty one if needed."""
    wallet = WALLETS.get(user_id)
    if wallet is None:
        wallet = Wallet(user_id=user_id)
        WALLETS[user_id] = wallet
    return wallet


def ensure_wallet(user_id: int, *, level: Optional[str] = None) -> Wallet:
    wallet = get_wallet(user_id)
    if level is not None:
        wallet.level = level
    return wallet


def earn_tokens(user_id: int, amount: int, *, note: str = "", actor_id: Optional[int] = None) -> Transaction:
    if amount <= 0:
        raise ValueError("amount must be positive")

    wallet = get_wallet(user_id)
    wallet.balance += amount
    wallet.tokens_earned += amount
    wallet.level = _resolve_level(wallet.balance)

    tx = Transaction(
        id=_next_tx_id(),
        ts=dt.datetime.utcnow(),
        kind="earn",
        amount=amount,
        actor_id=actor_id or user_id,
        counterparty_id=None,
        note=note,
    )
    wallet.record(tx)
    LEDGER.append(tx)

    METRICS["tokens_earned"] += amount
    return tx


def spend_tokens(user_id: int, amount: int, *, note: str = "", actor_id: Optional[int] = None) -> Transaction:
    if amount <= 0:
        raise ValueError("amount must be positive")

    wallet = get_wallet(user_id)
    if wallet.balance < amount:
        raise ValueError("insufficient balance")

    wallet.balance -= amount
    wallet.tokens_spent += amount
    wallet.level = _resolve_level(wallet.balance)

    tx = Transaction(
        id=_next_tx_id(),
        ts=dt.datetime.utcnow(),
        kind="spend",
        amount=amount,
        actor_id=actor_id or user_id,
        counterparty_id=None,
        note=note,
    )
    wallet.record(tx)
    LEDGER.append(tx)

    METRICS["tokens_spent"] += amount
    return tx


def transfer_tokens(sender_id: int, recipient_id: int, amount: int, *, note: str = "Перевод") -> Transaction:
    if sender_id == recipient_id:
        raise ValueError("cannot transfer to self")
    if amount <= 0:
        raise ValueError("amount must be positive")

    sender = get_wallet(sender_id)
    recipient = get_wallet(recipient_id)
    if sender.balance < amount:
        raise ValueError("insufficient balance")

    sender.balance -= amount
    sender.level = _resolve_level(sender.balance)
    recipient.balance += amount
    recipient.level = _resolve_level(recipient.balance)

    base_tx = Transaction(
        id=_next_tx_id(),
        ts=dt.datetime.utcnow(),
        kind="transfer",
        amount=amount,
        actor_id=sender_id,
        counterparty_id=recipient_id,
        note=note,
    )
    LEDGER.append(base_tx)

    sender_tx = Transaction(
        id=base_tx.id,
        ts=base_tx.ts,
        kind="transfer_out",
        amount=amount,
        actor_id=sender_id,
        counterparty_id=recipient_id,
        note=note,
    )
    recipient_tx = Transaction(
        id=base_tx.id,
        ts=base_tx.ts,
        kind="transfer_in",
        amount=amount,
        actor_id=sender_id,
        counterparty_id=recipient_id,
        note=note,
    )

    sender.record(sender_tx)
    recipient.record(recipient_tx)
    return base_tx


def get_wallet_history(user_id: int, limit: int = 10) -> List[Transaction]:
    wallet = get_wallet(user_id)
    return list(wallet.history)[:limit]


def iter_ledger(start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None) -> Iterable[Transaction]:
    for tx in LEDGER:
        if start and tx.ts < start:
            continue
        if end and tx.ts >= end:
            continue
        yield tx


def get_turnover_summary(
    day: Optional[dt.date] = None, *, tz: Optional[dt.tzinfo] = None
) -> dict:
    if tz is not None:
        target_day = day or dt.datetime.now(tz).date()
        start_local = dt.datetime.combine(target_day, dt.time.min, tzinfo=tz)
        end_local = start_local + dt.timedelta(days=1)
        start = start_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
        end = end_local.astimezone(dt.timezone.utc).replace(tzinfo=None)
    else:
        target_day = day or dt.datetime.utcnow().date()
        start = dt.datetime.combine(target_day, dt.time.min)
        end = start + dt.timedelta(days=1)

    earned = 0
    spent = 0
    transfers = 0

    for tx in iter_ledger(start, end):
        if tx.kind == "earn":
            earned += tx.amount
        elif tx.kind == "spend":
            spent += tx.amount
        elif tx.kind == "transfer":
            transfers += tx.amount

    net = earned - spent
    return {
        "day": target_day.isoformat(),
        "earned": earned,
        "spent": spent,
        "net": net,
        "transfers": transfers,
    }


def get_metrics() -> dict:
    return dict(METRICS)


def list_wallets() -> List[Wallet]:
    return list(WALLETS.values())


def reset_all() -> None:
    """Utility for tests to clear the in-memory state."""
    WALLETS.clear()
    LEDGER.clear()
    METRICS["tokens_earned"] = 0
    METRICS["tokens_spent"] = 0
