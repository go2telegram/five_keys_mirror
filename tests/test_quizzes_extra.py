from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import quiz_deficits, quiz_skin_joint, quiz_sleep, quiz_stress2


@asynccontextmanager
async def _dummy_scope():
    yield object()


def _make_callback(user_id: int, data: str) -> MagicMock:
    message = MagicMock()
    message.edit_text = AsyncMock()
    message.answer = AsyncMock()
    callback = MagicMock()
    callback.data = data
    callback.from_user = SimpleNamespace(id=user_id, username="tester")
    callback.message = message
    callback.answer = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_quiz_deficits_flow(monkeypatch):
    monkeypatch.setattr(quiz_deficits, "session_scope", _dummy_scope)
    monkeypatch.setattr(quiz_deficits.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(quiz_deficits, "set_last_plan", AsyncMock())
    monkeypatch.setattr(quiz_deficits.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(quiz_deficits, "send_product_cards", send_mock)

    user_id = 9101
    await quiz_deficits.quiz_deficits_start(_make_callback(user_id, "quiz:deficits"))

    for idx in range(len(quiz_deficits.QUESTIONS)):
        await quiz_deficits.quiz_deficits_step(_make_callback(user_id, f"q:deficits:{idx}:0"))

    quiz_deficits.set_last_plan.assert_awaited()
    quiz_deficits.events_repo.log.assert_awaited()
    send_mock.assert_awaited()
    assert user_id not in quiz_deficits.SESSIONS


@pytest.mark.asyncio
async def test_quiz_stress2_flow(monkeypatch):
    monkeypatch.setattr(quiz_stress2, "session_scope", _dummy_scope)
    monkeypatch.setattr(quiz_stress2.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(quiz_stress2, "set_last_plan", AsyncMock())
    monkeypatch.setattr(quiz_stress2.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(quiz_stress2, "send_product_cards", send_mock)

    user_id = 9202
    await quiz_stress2.quiz_stress2_start(_make_callback(user_id, "quiz:stress2"))
    for idx in range(len(quiz_stress2.QUESTIONS)):
        await quiz_stress2.quiz_stress2_step(_make_callback(user_id, f"q:stress2:{idx}:0"))

    quiz_stress2.set_last_plan.assert_awaited()
    quiz_stress2.events_repo.log.assert_awaited()
    send_mock.assert_awaited()


@pytest.mark.asyncio
async def test_quiz_skin_joint_flow(monkeypatch):
    monkeypatch.setattr(quiz_skin_joint, "session_scope", _dummy_scope)
    monkeypatch.setattr(quiz_skin_joint.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(quiz_skin_joint, "set_last_plan", AsyncMock())
    monkeypatch.setattr(quiz_skin_joint.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(quiz_skin_joint, "send_product_cards", send_mock)

    user_id = 9303
    await quiz_skin_joint.quiz_skin_joint_start(_make_callback(user_id, "quiz:skin_joint"))
    for idx in range(len(quiz_skin_joint.QUESTIONS)):
        await quiz_skin_joint.quiz_skin_joint_step(_make_callback(user_id, f"q:skin_joint:{idx}:0"))

    quiz_skin_joint.set_last_plan.assert_awaited()
    quiz_skin_joint.events_repo.log.assert_awaited()
    send_mock.assert_awaited()


def test_sleep_quiz_expanded():
    assert len(quiz_sleep.SLEEP_QUESTIONS) >= 9
