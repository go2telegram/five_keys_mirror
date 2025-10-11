"""Smoke tests for /start and home handlers."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import start
from app.main import _handle_ping, home_main


@pytest.mark.asyncio
async def test_start_safe_sends_greeting_and_schedules_background(monkeypatch):
    """The lightweight /start handler should reply immediately and schedule work."""

    recorded: dict[str, object] = {}
    scheduled: list[str] = []

    async def fake_answer(text: str, reply_markup=None):  # noqa: D401 - simple stub
        recorded["text"] = text
        recorded["reply_markup"] = reply_markup

    message = SimpleNamespace(
        text="/start",
        from_user=SimpleNamespace(id=4242, username="smoke"),
        answer=fake_answer,
    )

    def fake_create_task(coro):
        scheduled.append(getattr(coro.cr_code, "co_name", ""))
        coro.close()

        class _DoneTask:
            def cancel(self) -> None:  # noqa: D401 - stub
                return None

        return _DoneTask()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    await start.start_safe(message)

    assert recorded.get("text", "").startswith("👋 Привет!")
    assert recorded.get("reply_markup") is not None
    assert "_start_full" in scheduled


@pytest.mark.asyncio
async def test_home_main_falls_back_to_answer_on_edit_failure(monkeypatch):
    """home:main must gracefully send a fresh message when editing fails."""

    monkeypatch.setattr("app.main.safe_edit_text", AsyncMock(side_effect=RuntimeError("boom")))

    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        data="home:main",
        from_user=SimpleNamespace(id=5151, username="navigator"),
        message=message,
        answer=AsyncMock(),
    )

    await home_main(callback)

    message.answer.assert_awaited()
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_ping_contains_build_info() -> None:
    response = await _handle_ping(object())
    payload = json.loads(response.text)
    assert payload["status"] == "ok"
    assert payload["version"]
    assert payload["commit"]
    assert payload["time"]
