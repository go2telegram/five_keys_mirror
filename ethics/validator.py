"""Rule-based validator for automated actions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

import yaml


@dataclass(slots=True)
class EthicsViolation(Exception):
    """Raised when an action violates the ethics policy."""

    action: str
    reason: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover - human readable helper
        parts = [f"Action '{self.action}' is not permitted: {self.reason}."]
        if self.details:
            parts.append(f"Details: {self.details}")
        return " ".join(parts)


class EthicsValidator:
    """Validates actions against YAML-defined rules."""

    def __init__(
        self,
        rules_path: str | Path | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._rules_path = Path(rules_path) if rules_path else Path(__file__).resolve().parent / "rules.yml"
        self.enabled = enabled
        self._lock = Lock()
        self._violations = 0
        self._allowed: set[str] = set()
        self._forbidden: set[str] = set()
        self.reload()

    # --- rules management -------------------------------------------------
    def reload(self) -> None:
        """Reload rules from disk."""
        with self._lock:
            data = self._load_rules()
            self._allowed = set(self._normalise(data.get("allowed_actions", [])))
            self._forbidden = set(self._normalise(data.get("forbidden_actions", [])))

    def _load_rules(self) -> dict[str, Any]:
        if not self._rules_path.exists():
            return {}
        raw = self._rules_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            raise ValueError("Ethics rules file must contain a mapping at the top level")
        return data

    @staticmethod
    def _normalise(items: Iterable[str]) -> Iterable[str]:
        for item in items:
            if not isinstance(item, str):
                continue
            val = item.strip()
            if val:
                yield val

    # --- validation -------------------------------------------------------
    def ensure_allowed(self, action: str, *, details: dict[str, Any] | None = None) -> None:
        """Ensure that the action is allowed. Raises :class:`EthicsViolation` otherwise."""

        if not self.enabled:
            return

        action_key = action.strip()
        if not action_key:
            raise ValueError("Action name must be a non-empty string")

        violation_reason: str | None = None
        with self._lock:
            if action_key in self._forbidden:
                violation_reason = "действие находится в forbidden_actions"
            elif action_key not in self._allowed:
                violation_reason = "действие не перечислено в allowed_actions"

            if violation_reason:
                self._violations += 1

        if violation_reason:
            raise EthicsViolation(action=action_key, reason=violation_reason, details=details)

    # --- stats ------------------------------------------------------------
    @property
    def violations(self) -> int:
        with self._lock:
            return self._violations

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "violations": self.violations,
            "rules_path": str(self._rules_path),
        }


__all__ = ["EthicsValidator", "EthicsViolation"]
