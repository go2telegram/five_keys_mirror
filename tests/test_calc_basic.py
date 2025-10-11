from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import calc


@asynccontextmanager
async def _dummy_scope():
    yield object()


def _make_message(user_id: int, text: str):
    message = MagicMock()
    message.from_user = SimpleNamespace(id=user_id, username="tester")
    message.text = text
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_msd_success_saves_plan_and_cards(monkeypatch):
    monkeypatch.setattr(calc, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(calc, "send_product_cards", send_mock)

    user_id = 101
    calc.SESSIONS[user_id] = {"calc": "msd"}
    message = _make_message(user_id, "165 Ж")

    await calc.handle_calc_message(message)

    calc.set_last_plan.assert_awaited()
    calc.events_repo.log.assert_awaited()
    send_mock.assert_awaited()
    _, kwargs = send_mock.await_args
    assert kwargs["back_cb"] == "calc:menu"
    assert user_id not in calc.SESSIONS


@pytest.mark.asyncio
async def test_msd_invalid_input_prompts_retry(monkeypatch):
    monkeypatch.setattr(calc, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc.events_repo, "log", AsyncMock())
    monkeypatch.setattr(calc, "send_product_cards", AsyncMock())

    user_id = 202
    calc.SESSIONS[user_id] = {"calc": "msd"}
    message = _make_message(user_id, "рост 165")

    await calc.handle_calc_message(message)

    message.answer.assert_awaited()
    assert user_id in calc.SESSIONS
    calc.SESSIONS.pop(user_id, None)
