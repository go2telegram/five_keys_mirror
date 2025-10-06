import asyncio
import hashlib
import hmac
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import settings
from app.health import create_web_app
from app.handlers import tribute_webhook as h_tw


def _signed_body(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    secret = settings.TRIBUTE_API_KEY.encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return body, signature


@pytest.fixture(autouse=True)
def reset_rate_limit() -> None:
    h_tw._RATE_BUCKETS.clear()
    yield
    h_tw._RATE_BUCKETS.clear()


def test_webhook_requires_signature() -> None:
    async def runner() -> None:
        app = create_web_app()
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                payload = {"name": "new_subscription", "payload": {}}
                response = await client.post(
                    settings.TRIBUTE_WEBHOOK_PATH,
                    data=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                assert response.status == 401
                data = await response.json()
        assert data["reason"] == "missing_signature"

    asyncio.run(runner())


def test_webhook_rejects_invalid_signature() -> None:
    async def runner() -> None:
        app = create_web_app()
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                payload = {"name": "new_subscription", "payload": {}}
                body, _ = _signed_body(payload)
                response = await client.post(
                    settings.TRIBUTE_WEBHOOK_PATH,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "trbt-signature": "bad-signature",
                    },
                )
                assert response.status == 401
                data = await response.json()
        assert data["reason"] == "invalid_signature"

    asyncio.run(runner())


def test_webhook_accepts_valid_signature() -> None:
    async def runner() -> None:
        app = create_web_app()
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                payload = {
                    "name": "new_subscription",
                    "payload": {
                        "telegram_user_id": 123456,
                        "subscription_name": "MITO Basic",
                        "expires_at": "2099-12-31T00:00:00Z",
                    },
                }
                body, signature = _signed_body(payload)
                response = await client.post(
                    settings.TRIBUTE_WEBHOOK_PATH,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "trbt-signature": signature,
                    },
                )
                assert response.status == 200
                data = await response.json()
        assert data == {"ok": True}

    asyncio.run(runner())


def test_webhook_rate_limits_repeated_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(h_tw, "_RATE_LIMIT_MAX", 2)

    async def runner() -> None:
        app = create_web_app()
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                payload = {
                    "name": "new_subscription",
                    "payload": {
                        "telegram_user_id": 777,
                        "subscription_name": "MITO Basic",
                    },
                }
                body, signature = _signed_body(payload)
                headers = {
                    "Content-Type": "application/json",
                    "trbt-signature": signature,
                }
                for _ in range(2):
                    response_ok = await client.post(
                        settings.TRIBUTE_WEBHOOK_PATH,
                        data=body,
                        headers=headers,
                    )
                    assert response_ok.status == 200
                    await response_ok.json()
                response = await client.post(
                    settings.TRIBUTE_WEBHOOK_PATH,
                    data=body,
                    headers=headers,
                )
                assert response.status == 429
                data = await response.json()
        assert data["reason"] == "rate_limited"

    asyncio.run(runner())
