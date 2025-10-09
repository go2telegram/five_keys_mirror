from __future__ import annotations

from app.config import settings
from app.db.types import EncryptedString
from app.security.pii import Fernet


def test_encrypted_string_roundtrip(monkeypatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "PII_KEY", key, raising=False)

    column = EncryptedString()
    secret = "+79990001122"
    token = column.process_bind_param(secret, None)
    assert isinstance(token, str)
    assert token != secret

    restored = column.process_result_value(token, None)
    assert restored == secret
