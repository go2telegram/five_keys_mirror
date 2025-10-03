from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import tribute_webhook


@asynccontextmanager
async def _dummy_scope():
    yield SimpleNamespace()


class _DummyRequest:
    def __init__(self, payload: dict, signature: str):
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = {"trbt-signature": signature}

    async def read(self) -> bytes:  # pragma: no cover - exercised in tests
        return self._raw


def _sign(payload: dict, secret: str) -> str:
    body = json.dumps(payload).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_tribute_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(tribute_webhook, "INSECURE", False)
    monkeypatch.setattr(tribute_webhook.settings, "TRIBUTE_API_KEY", "secret")

    request = _DummyRequest({"name": "ping"}, "bad")
    response = await tribute_webhook.tribute_webhook(request)

    assert response.status == 401
    assert json.loads(response.text)["ok"] is False


@pytest.mark.asyncio
async def test_tribute_new_subscription_activates_plan(monkeypatch):
    secret = "secret"
    payload = {
        "name": "new_subscription",
        "payload": {
            "telegram_user_id": 123,
            "subscription_name": "MITO Pro",
            "expires_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    signature = _sign(payload, secret)

    request = _DummyRequest(payload, f"sha256={signature}")

    monkeypatch.setattr(tribute_webhook, "INSECURE", False)
    monkeypatch.setattr(tribute_webhook, "NOTIFY", True)
    monkeypatch.setattr(tribute_webhook.settings, "TRIBUTE_API_KEY", secret)
    monkeypatch.setattr(tribute_webhook, "session_scope", _dummy_scope)
    monkeypatch.setattr(tribute_webhook.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(tribute_webhook.subscriptions_repo, "set_plan", AsyncMock())
    monkeypatch.setattr(tribute_webhook.referrals_repo, "get_by_invited", AsyncMock(return_value=None))
    monkeypatch.setattr(tribute_webhook.events_repo, "log", AsyncMock())
    notify_mock = AsyncMock()
    monkeypatch.setattr(tribute_webhook, "_notify_user", notify_mock)

    response = await tribute_webhook.tribute_webhook(request)

    assert response.status == 200
    assert json.loads(response.text)["ok"] is True
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_tribute_cancelled_subscription_notifies(monkeypatch):
    secret = "secret"
    until = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "name": "cancelled_subscription",
        "payload": {
            "telegram_user_id": 321,
            "expires_at": until.isoformat(),
        },
    }
    signature = _sign(payload, secret)

    request = _DummyRequest(payload, signature)

    monkeypatch.setattr(tribute_webhook, "INSECURE", False)
    monkeypatch.setattr(tribute_webhook, "NOTIFY", True)
    monkeypatch.setattr(tribute_webhook.settings, "TRIBUTE_API_KEY", secret)
    monkeypatch.setattr(tribute_webhook, "session_scope", _dummy_scope)
    monkeypatch.setattr(
        tribute_webhook.subscriptions_repo,
        "get",
        AsyncMock(return_value=SimpleNamespace(until=until)),
    )
    monkeypatch.setattr(tribute_webhook.events_repo, "log", AsyncMock())
    notify_mock = AsyncMock()
    monkeypatch.setattr(tribute_webhook, "_notify_cancel", notify_mock)

    response = await tribute_webhook.tribute_webhook(request)

    assert response.status == 200
    assert json.loads(response.text)["ok"] is True
    notify_mock.assert_awaited_once()
