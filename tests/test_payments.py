from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.services import payments


@asynccontextmanager
async def _dummy_scope():
    yield SimpleNamespace()


@pytest.mark.asyncio
async def test_send_invoice_creates_order(monkeypatch):
    message = MagicMock()
    message.from_user = SimpleNamespace(id=101, username="demo")
    message.answer_invoice = AsyncMock()

    monkeypatch.setattr(payments, "session_scope", _dummy_scope)
    monkeypatch.setattr(payments.users_repo, "get_or_create_user", AsyncMock())
    order = SimpleNamespace(id=55)
    monkeypatch.setattr(payments.orders_repo, "create", AsyncMock(return_value=order))
    monkeypatch.setattr(payments.orders_repo, "attach_payload", AsyncMock())
    monkeypatch.setattr(payments, "commit_safely", AsyncMock())
    monkeypatch.setattr(payments.settings, "TELEGRAM_PROVIDER_TOKEN", "token123")

    gateway = payments.TelegramPremiumGateway(message.bot)
    sent = await gateway.send_invoice(message, "basic")

    assert sent is True
    message.answer_invoice.assert_awaited()
    args, kwargs = message.answer_invoice.await_args
    assert "payload" in kwargs
    payload = kwargs["payload"]
    assert str(order.id) in payload


@pytest.mark.asyncio
async def test_finalize_successful_payment_idempotent(monkeypatch):
    payload_base = {
        "user_id": 202,
        "plan": "basic",
        "amount": payments.settings.PREMIUM_BASIC_AMOUNT,
        "currency": payments.settings.PREMIUM_DEFAULT_CURRENCY,
        "nonce": "deadbeef",
    }
    signature = payments.sign_payload(payload_base)
    payload_base.update({"signature": signature})

    monkeypatch.setattr(payments, "session_scope", _dummy_scope)
    order = SimpleNamespace()
    monkeypatch.setattr(payments.orders_repo, "get_by_payload_hash", AsyncMock(return_value=order))
    monkeypatch.setattr(payments.orders_repo, "update_status", AsyncMock())
    monkeypatch.setattr(payments.users_repo, "get_or_create_user", AsyncMock())
    existing = SimpleNamespace(txn_id=None)
    monkeypatch.setattr(payments.subscriptions_repo, "get", AsyncMock(return_value=existing))
    monkeypatch.setattr(payments.subscriptions_repo, "set_plan", AsyncMock())
    monkeypatch.setattr(payments, "commit_safely", AsyncMock())

    plan = await payments.finalize_successful_payment(payload_base, provider_charge_id="txn-1")
    assert plan.code == "basic"
    payments.subscriptions_repo.set_plan.assert_awaited()

    payments.subscriptions_repo.set_plan.reset_mock()
    existing.txn_id = "txn-1"
    await payments.finalize_successful_payment(payload_base, provider_charge_id="txn-1")
    payments.subscriptions_repo.set_plan.assert_not_called()
