"""Utilities for validating outbound requests to external AI systems."""
from __future__ import annotations

import re
from dataclasses import dataclass


class EthicsViolation(Exception):
    """Raised when a query violates outbound communication policies."""


@dataclass(slots=True)
class EthicsVerdict:
    """Result of ethics validation."""

    is_allowed: bool
    reason: str | None = None


_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(hack|ddos|exploit)\b"),
    re.compile(r"(?i)\bweapons?\b"),
    re.compile(r"(?i)\b(personal data|passport|ssn)\b"),
)


def validate_query(text: str) -> EthicsVerdict:
    """Check that *text* is allowed to be sent to external AI providers."""
    if not text or not text.strip():
        return EthicsVerdict(False, "Запрос не должен быть пустым.")

    cleaned = text.strip()
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(cleaned):
            return EthicsVerdict(False, "Запрос содержит запрещённую тему.")

    if len(cleaned) > 2000:
        return EthicsVerdict(False, "Запрос слишком длинный — сократите формулировку.")

    return EthicsVerdict(True)


def ensure_allowed(text: str) -> str:
    """Validate *text* and return a cleaned version or raise :class:`EthicsViolation`."""
    verdict = validate_query(text)
    if not verdict.is_allowed:
        raise EthicsViolation(verdict.reason or "Запрос отклонён политикой безопасности.")
    return text.strip()
