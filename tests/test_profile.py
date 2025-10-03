from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import profile


@asynccontextmanager
def _dummy_scope():
    yield object()


def _collect_callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]


@pytest.mark.asyncio
async def test_profile_renders_core_information(monkeypatch):
    monkeypatch.setattr(profile, "session_scope", _dummy_scope)
    user = SimpleNamespace(id=111, username="tester")
    monkeypatch.setattr(
        profile.users_repo,
        "get_or_create_user",
        AsyncMock(return_value=user),
    )

    until = datetime.now(timezone.utc)
    subscription = SimpleNamespace(plan="pro", until=until)
    monkeypatch.setattr(
        profile.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(True, subscription)),
    )
    monkeypatch.setattr(
        profile.referrals_repo,
        "stats_for_referrer",
        AsyncMock(return_value=(5, 2)),
    )

    plan_event = SimpleNamespace(meta={"title": "План энергии"}, ts=until)
    monkeypatch.setattr(
        profile.events_repo,
        "recent_plans",
        AsyncMock(return_value=[plan_event]),
    )

    async def _last_by(_session, _user_id, name):
        if name == "notify_on":
            return SimpleNamespace(ts=until)
        return None

    monkeypatch.setattr(profile.events_repo, "last_by", _last_by)

    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=111, username="tester")
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await profile.profile_open(callback)

    callback.answer.assert_awaited()
    callback.message.edit_text.assert_awaited()
    args, kwargs = callback.message.edit_text.await_args
    rendered = args[0]
    assert "ID: <code>111</code>" in rendered
    assert "План энергии" in rendered
    callbacks = _collect_callbacks(kwargs["reply_markup"])
    assert "notify:off" in callbacks
    assert "home:main" in callbacks
