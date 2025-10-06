"""Helpers for signing and validating callback payloads."""
from __future__ import annotations

import base64
import hmac
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Optional

from aiogram.filters import Filter
from aiogram.types import CallbackQuery

from app.config import settings

_DELIMITER = "|"
_SIGNATURE_BYTES = 16


def _get_secret() -> bytes:
    secret = settings.get_callback_secret()
    if not secret:
        raise RuntimeError("Callback secret is not configured")
    return secret.encode("utf-8")


def _encode_signature(data: str, secret: bytes) -> str:
    digest = hmac.new(secret, data.encode("utf-8"), sha256).digest()
    shortened = digest[:_SIGNATURE_BYTES]
    encoded = base64.urlsafe_b64encode(shortened).decode("ascii")
    return encoded.rstrip("=")


def _compose(payload: str, expires_at: int) -> str:
    return f"{payload}{_DELIMITER}{expires_at}"


@dataclass(slots=True)
class SignedPayload:
    """Validated callback payload with expiration metadata."""

    value: str
    expires_at: int

    def is_expired(self, now: Optional[int] = None) -> bool:
        if now is None:
            now = int(time.time())
        return now > self.expires_at


def sign(payload: str, ttl: int = 300) -> str:
    if ttl <= 0:
        raise ValueError("TTL must be a positive integer")

    expires_at = int(time.time()) + ttl
    secret = _get_secret()
    data = _compose(payload, expires_at)
    signature = _encode_signature(data, secret)
    return f"{data}{_DELIMITER}{signature}"


def verify(token: Optional[str]) -> Optional[SignedPayload]:
    if not token:
        return None

    try:
        payload, expires_raw, signature = token.rsplit(_DELIMITER, 2)
    except ValueError:
        return None

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None

    secret = _get_secret()
    data = _compose(payload, expires_at)
    expected_signature = _encode_signature(data, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    return SignedPayload(value=payload, expires_at=expires_at)


class SignedAction(Filter):
    """Aiogram filter that validates signed callback payloads."""

    def __init__(self, action: str):
        self.action = action

    async def __call__(self, callback: CallbackQuery) -> bool | dict:
        signed = verify(callback.data)
        if not signed or signed.value != self.action:
            return False
        return {"signed": signed}


__all__ = ["sign", "verify", "SignedPayload", "SignedAction"]
