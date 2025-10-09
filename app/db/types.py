"""Custom SQLAlchemy column types."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.types import String, TypeDecorator

from app.security.pii import decrypt, encrypt, get_fernet, PIIConfigurationError

_log = logging.getLogger("db")


class EncryptedString(TypeDecorator[str]):
    """A SQLAlchemy type that transparently encrypts/decrypts strings."""

    impl = String
    cache_ok = False

    def __init__(self, length: int = 512) -> None:
        super().__init__(length)
        self.length = length

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # pragma: no cover - SQLAlchemy hook
        if value is None:
            return None
        try:
            return encrypt(str(value))
        except PIIConfigurationError as exc:
            raise RuntimeError("PII_KEY is required to store encrypted data") from exc

    def process_result_value(self, value: Any, dialect: Any) -> Any:  # pragma: no cover - SQLAlchemy hook
        if value is None:
            return None
        try:
            get_fernet()
        except PIIConfigurationError as exc:
            _log.error("PII_KEY missing while reading encrypted data")
            raise RuntimeError("PII_KEY is required to read encrypted data") from exc
        return decrypt(str(value))


__all__ = ["EncryptedString"]
