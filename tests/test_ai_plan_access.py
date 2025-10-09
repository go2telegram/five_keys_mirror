from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import premium


@asynccontextmanager
def _dummy_scope():
    yield SimpleNamespace()


@pytest.mark.asyncio
async def test_ai_plan_requires_premium_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(premium, "session_scope", _dummy_scope)
    monkeypatch.setattr(premium.subscriptions_repo, "is_active", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(premium, "build_ai_plan", AsyncMock())

    message = SimpleNamespace()
    message.from_user = SimpleNamespace(id=501)
    message.answer = AsyncMock()

    await premium.ai_plan_cmd(message)

    message.answer.assert_awaited()
    assert message.answer.await_count == 1
    assert "только подписчикам" in message.answer.await_args_list[0][0][0]
    premium.build_ai_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_plan_for_premium_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(premium, "session_scope", _dummy_scope)
    monkeypatch.setattr(
        premium.subscriptions_repo,
        "is_active",
        AsyncMock(return_value=(True, SimpleNamespace(plan="pro"))),
    )
    build_mock = AsyncMock(return_value="## plan body")
    monkeypatch.setattr(premium, "build_ai_plan", build_mock)
    monkeypatch.setattr(premium, "split_md", lambda text, limit: [text])
    monkeypatch.setattr(premium.events_repo, "log", AsyncMock())
    monkeypatch.setattr(premium, "commit_safely", AsyncMock())

    message = SimpleNamespace()
    message.from_user = SimpleNamespace(id=777)
    message.answer = AsyncMock()

    await premium.ai_plan_cmd(message)

    build_mock.assert_awaited_once()
    assert message.answer.await_count >= 2
    first_payload = message.answer.await_args_list[0][0][0]
    assert "Собираю" in first_payload
    second_payload = message.answer.await_args_list[1][0][0]
    assert "## plan body" in second_payload
    premium.events_repo.log.assert_awaited()
    premium.commit_safely.assert_awaited()
