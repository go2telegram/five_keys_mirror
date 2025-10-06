"""Policy package exposing a shared policy engine instance."""
from __future__ import annotations

from .engine import PolicyEngine

_policy_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    """Return a singleton instance of :class:`PolicyEngine`."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine


__all__ = ["PolicyEngine", "get_policy_engine"]
