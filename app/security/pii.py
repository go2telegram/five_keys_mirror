"""Helpers for encrypting and decrypting personally identifiable information."""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import logging
import os
import time
from typing import Callable

try:  # pragma: no cover - executed in environments with cryptography installed
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path for sandboxed tests

    class InvalidToken(Exception):
        """Raised when decrypting malformed tokens."""

    class Fernet:  # type: ignore[override]
        """Lightweight, insecure-compatible fallback when cryptography is unavailable."""

        def __init__(self, key: bytes) -> None:
            try:
                self._key = base64.urlsafe_b64decode(key)
            except Exception as exc:  # pragma: no cover - invalid key format
                raise ValueError("Fernet key must be base64-urlsafe encoded") from exc
            if len(self._key) < 32:
                raise ValueError("Fernet key must decode to at least 32 bytes")

        @staticmethod
        def generate_key() -> bytes:
            return base64.urlsafe_b64encode(os.urandom(32))

        def encrypt(self, data: bytes) -> bytes:
            timestamp = int(time.time()).to_bytes(8, "big")
            salt = os.urandom(16)
            digest = hashlib.sha256(self._key + timestamp + salt + data).digest()
            token = base64.urlsafe_b64encode(timestamp + salt + data + digest)
            return token

        def decrypt(self, token: bytes) -> bytes:
            try:
                raw = base64.urlsafe_b64decode(token)
            except Exception as exc:  # pragma: no cover - invalid token
                raise InvalidToken("Invalid token") from exc
            if len(raw) < 8 + 16 + 32:
                raise InvalidToken("Token too short")
            timestamp = raw[:8]
            salt = raw[8:24]
            data = raw[24:-32]
            digest = raw[-32:]
            expected = hashlib.sha256(self._key + timestamp + salt + data).digest()
            if not hmac.compare_digest(digest, expected):
                raise InvalidToken("Signature mismatch")
            return data

from app.config import settings

_log = logging.getLogger("pii")


class PIIConfigurationError(RuntimeError):
    """Raised when the application is missing the encryption key."""


@functools.lru_cache(maxsize=1)
def _build_fernet(key: str) -> Fernet:
    sanitized = key.strip()
    if not sanitized:
        raise PIIConfigurationError("PII_KEY is not configured")
    try:
        return Fernet(sanitized.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - cryptography raises ValueError
        raise PIIConfigurationError("Invalid PII_KEY provided") from exc


def get_fernet() -> Fernet:
    """Return a cached Fernet instance initialised with the configured key."""

    return _build_fernet(settings.PII_KEY)


def encrypt(value: str) -> str:
    """Encrypt a string value using Fernet."""

    if value is None:
        raise ValueError("value must not be None")
    token = get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(value: str, *, fallback: Callable[[], str | None] | None = None) -> str | None:
    """Decrypt a string value previously produced by :func:`encrypt`."""

    if value is None:
        return None
    try:
        decrypted = get_fernet().decrypt(value.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        _log.error("Failed to decrypt PII blob")
        if fallback is not None:
            return fallback()
        raise


__all__ = ["PIIConfigurationError", "decrypt", "encrypt", "get_fernet"]
