from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import premium
from app.handlers.guards import PREMIUM_REQUIRED_TEXT


@pytest.mark.asyncio
async def test_ai_plan_command_requires_premium(monkeypatch):
    message = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=77),
        bot=SimpleNamespace(),
    )
    mock_build = AsyncMock(return_value="## plan")
    monkeypatch.setattr(premium, "build_ai_plan", mock_build)

    await premium.ai_plan_cmd(message)

    message.answer.assert_awaited_once_with(PREMIUM_REQUIRED_TEXT)
    mock_build.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_plan_command_sends_plan_for_premium(monkeypatch):
    message = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=55),
        bot=SimpleNamespace(),
        entitlements={"premium": True},
    )
    mock_build = AsyncMock(return_value="## Weekly plan\nLine 2")
    monkeypatch.setattr(premium, "build_ai_plan", mock_build)

    await premium.ai_plan_cmd(message)

    assert message.answer.await_count == 2
    first_call = message.answer.await_args_list[0]
    second_call = message.answer.await_args_list[1]
    assert "Собираю" in first_call.args[0]
    assert second_call.kwargs.get("parse_mode") == "Markdown"
    mock_build.assert_awaited_once_with(55, "7d")
