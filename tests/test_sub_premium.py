from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import premium, subscription


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


@asynccontextmanager
def _dummy_scope():
    yield object()


@pytest.mark.asyncio
async def test_subscription_check_shows_active_plan(monkeypatch):
    monkeypatch.setattr(subscription, "session_scope", _dummy_scope)
    monkeypatch.setattr(subscription.users_repo, "get_or_create_user", AsyncMock())
    until = datetime.now(timezone.utc) + timedelta(days=3)
    sub = SimpleNamespace(plan="basic", until=until)
    monkeypatch.setattr(
        subscription.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(True, sub)),
    )

    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=42, username="demo")
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await subscription.sub_check(callback)

    callback.answer.assert_awaited()
    callback.message.edit_text.assert_awaited()
    args, kwargs = callback.message.edit_text.await_args
    assert "Подписка активна" in args[0]
    callbacks = [btn.callback_data for btn in _flatten(kwargs["reply_markup"]) if btn.callback_data]
    assert "sub:check" in callbacks
    assert "home:main" in callbacks


@pytest.mark.asyncio
async def test_subscription_check_handles_missing_plan(monkeypatch):
    monkeypatch.setattr(subscription, "session_scope", _dummy_scope)
    monkeypatch.setattr(subscription.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(
        subscription.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(False, None)),
    )

    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=99, username="ghost")
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await subscription.sub_check(callback)

    callback.message.edit_text.assert_awaited()
    args, kwargs = callback.message.edit_text.await_args
    callbacks = [btn.callback_data for btn in _flatten(kwargs["reply_markup"]) if btn.callback_data]
    assert "sub:check" in callbacks
    assert "home:main" in callbacks


@pytest.mark.asyncio
async def test_premium_menu_requires_subscription(monkeypatch):
    monkeypatch.setattr(premium, "session_scope", _dummy_scope)
    monkeypatch.setattr(premium.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(
        premium.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(False, None)),
    )

    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=10, username="tester")
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await premium.premium_menu(callback)

    callback.message.edit_text.assert_awaited()
    args, kwargs = callback.message.edit_text.await_args
    assert "Premium доступен" in args[0]
    callbacks = [btn.callback_data for btn in _flatten(kwargs["reply_markup"]) if btn.callback_data]
    assert "sub:menu" in callbacks
    assert "home:main" in callbacks


@pytest.mark.asyncio
async def test_premium_menu_shows_links_for_active_user(monkeypatch):
    monkeypatch.setattr(premium, "session_scope", _dummy_scope)
    monkeypatch.setattr(premium.users_repo, "get_or_create_user", AsyncMock())
    sub = SimpleNamespace(plan="pro", until=datetime.now(timezone.utc) + timedelta(days=30))
    monkeypatch.setattr(
        premium.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(True, sub)),
    )

    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=11, username="vip")
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await premium.premium_menu(callback)

    callback.message.edit_text.assert_awaited()
    args, kwargs = callback.message.edit_text.await_args
    assert "MITO Pro" in args[0]
    urls = [btn.url for btn in _flatten(kwargs["reply_markup"]) if btn.url]
    assert any(url.startswith("https://t.me/") for url in urls)
