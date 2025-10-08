from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import quiz_sleep
from app.quiz.engine import answer_callback, load_quiz, start_quiz


@asynccontextmanager
async def _dummy_scope():
    yield object()


@pytest.mark.asyncio
async def test_sleep_quiz_flow(monkeypatch):
    monkeypatch.setattr(quiz_sleep, "compat_session", lambda *_args, **_kwargs: _dummy_scope())
    monkeypatch.setattr(quiz_sleep.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(quiz_sleep, "set_last_plan", AsyncMock())
    monkeypatch.setattr(quiz_sleep.events_repo, "log", AsyncMock())
    monkeypatch.setattr(quiz_sleep, "product_lines", lambda codes, ctx: [f"{ctx}:{code}" for code in codes])
    monkeypatch.setattr(quiz_sleep, "pick_for_context", lambda *args, **kwargs: ["card"])
    send_mock = AsyncMock()
    monkeypatch.setattr(quiz_sleep, "send_product_cards", send_mock)

    storage = MemoryStorage()
    state = FSMContext(storage, StorageKey(bot_id=1, chat_id=1, user_id=42))

    message = MagicMock()
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    message.answer_media_group = AsyncMock()
    message.delete = AsyncMock()

    definition = load_quiz("sleep")
    await start_quiz(message, state, "sleep")

    callback = MagicMock()
    callback.message = message
    callback.answer = AsyncMock()
    callback.from_user = SimpleNamespace(id=42, username="tester")

    for idx, question in enumerate(definition.questions):
        callback.data = f"tests:answer:sleep:{idx}:{len(question.options) - 1}"
        await answer_callback(callback, state)

    summary_calls = [call for call in message.answer.await_args_list if call.args and "Сумма баллов" in call.args[0]]
    assert summary_calls, "summary message with score was not sent"
    summary_text = summary_calls[-1].args[0]
    assert "Сумма баллов" in summary_text
    severe_threshold = definition.thresholds[-1]
    assert severe_threshold.label in summary_text
    assert severe_threshold.advice in summary_text
    for tag in ("sleep_support", "sleep_calm", "magnesium", "glycine", "mct"):
        assert f"#{tag}" in summary_text

    send_mock.assert_awaited_once()
    quiz_sleep.events_repo.log.assert_awaited()
    quiz_sleep.set_last_plan.assert_awaited()
    assert await state.get_state() is None
