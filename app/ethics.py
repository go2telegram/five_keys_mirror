"""Application-level access to the ethics validator."""
from __future__ import annotations

from ethics.validator import EthicsValidator, EthicsViolation

from app.config import settings


ethics_validator = EthicsValidator(enabled=getattr(settings, "ENABLE_ETHICS", True))

__all__ = ["ethics_validator", "EthicsViolation", "EthicsValidator"]
