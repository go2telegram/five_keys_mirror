"""Minimal smoke coverage for calculator and quiz flows."""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import calc, calc_unified
from app.quiz import engine as quiz_engine
from app.quiz.engine import answer_callback, build_answer_callback_data, load_quiz, start_quiz


@asynccontextmanager
async def _dummy_scope():
    yield object()


def _install_yaml_stub() -> None:
    if "yaml" in sys.modules:
        return

    class _YamlStub:
        @staticmethod
        def safe_load(stream):
            data = stream.read() if hasattr(stream, "read") else stream
            return json.loads(data)

        @staticmethod
        def safe_dump(data, stream, allow_unicode=False, **kwargs):  # noqa: ARG001 - signature compat
            json.dump(data, stream)

    sys.modules["yaml"] = _YamlStub()


_install_yaml_stub()


class DummyMessage:
    _next_id = 0

    def __init__(self) -> None:
        type(self)._next_id += 1
        self.message_id = type(self)._next_id
        self.children: list[DummyMessage] = []
        self.text: str | None = None
        self.caption: str | None = None
        self.reply_markup = None
        self.deleted = False

    async def answer(self, text: str, reply_markup=None):
        child = DummyMessage()
        child.text = text
        child.reply_markup = reply_markup
        self.children.append(child)
        return child

    async def answer_photo(self, photo, caption: str, reply_markup=None):  # noqa: D401 - stub
        child = DummyMessage()
        child.caption = caption
        child.reply_markup = reply_markup
        self.children.append(child)
        return child

    async def delete(self) -> None:  # noqa: D401 - stub
        self.deleted = True


class DummyCallback:
    def __init__(self, data: str, message: DummyMessage, user_id: int = 1, username: str = "tester") -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self._answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self._answers.append((text, show_alert))


def _make_message(user_id: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id, username="tester"),
        answer=AsyncMock(),
    )


def _make_callback(user_id: int, data: str) -> SimpleNamespace:
    message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock(), from_user=SimpleNamespace(id=user_id))
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, username="tester"),
        message=message,
        answer=AsyncMock(),
    )


def _patch_calc_infrastructure(monkeypatch):
    monkeypatch.setattr(calc, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc.events_repo, "log", AsyncMock())
    send_cards = AsyncMock()
    monkeypatch.setattr(calc, "send_product_cards", send_cards)
    premium_mock = AsyncMock()
    monkeypatch.setattr(calc, "send_premium_cta", premium_mock)
    monkeypatch.setattr(calc, "get_register_link", AsyncMock(return_value="https://example.com/register"))
    return send_cards, premium_mock


def _patch_calc_unified_infrastructure(monkeypatch):
    monkeypatch.setattr(calc_unified, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc_unified.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc_unified, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc_unified.events_repo, "log", AsyncMock())
    send_cards = AsyncMock()
    monkeypatch.setattr(calc_unified, "send_product_cards", send_cards)
    premium_mock = AsyncMock()
    monkeypatch.setattr(calc_unified, "send_premium_cta", premium_mock)
    monkeypatch.setattr(calc_unified, "get_register_link", AsyncMock(return_value="https://example.com/register"))
    monkeypatch.setattr(calc_unified, "safe_edit_text", AsyncMock())
    return send_cards, premium_mock


@pytest.mark.asyncio
async def test_msd_calculator_smoke(monkeypatch):
    send_cards, premium_mock = _patch_calc_infrastructure(monkeypatch)

    user_id = 9001
    calc.SESSIONS[user_id] = {"calc": "msd"}
    message = _make_message(user_id, "170 М")

    await calc.handle_calc_message(message)

    calc.set_last_plan.assert_awaited()
    calc.events_repo.log.assert_awaited()
    send_cards.assert_awaited()
    premium_mock.assert_awaited()
    assert user_id not in calc.SESSIONS


@pytest.mark.asyncio
async def test_bmi_calculator_smoke(monkeypatch):
    send_cards, premium_mock = _patch_calc_unified_infrastructure(monkeypatch)

    user_id = 9002
    calc_unified.SESSIONS.pop(user_id, None)
    start_cb = _make_callback(user_id, "calc:bmi")

    await calc_unified._start_flow(start_cb, "bmi")

    await calc_unified._dispatch_message(_make_message(user_id, "180"))
    await calc_unified._dispatch_message(_make_message(user_id, "78"))

    calc_unified.set_last_plan.assert_awaited()
    calc_unified.events_repo.log.assert_awaited()
    send_cards.assert_awaited()
    premium_mock.assert_awaited()
    assert calc_unified.SESSIONS.get(user_id) is None


def _write_quiz(tmp_path):
    questions = []
    for idx in range(5):
        questions.append(
            {
                "id": f"q{idx + 1}",
                "text": f"Question {idx + 1}?",
                "options": [
                    {"key": "a", "text": "Option A", "score": 1, "tags": [f"tag{idx + 1}"]},
                    {"key": "b", "text": "Option B", "score": 2, "tags": []},
                ],
            }
        )

    content = {
        "title": "Sample Quiz",
        "questions": questions,
        "result": {
            "thresholds": [
                {"min": 0, "max": 5, "label": "Low", "advice": "Rest", "tags": ["low"]},
                {"min": 6, "max": 10, "label": "Mid", "advice": "Keep", "tags": ["mid"]},
                {"min": 11, "max": 15, "label": "High", "advice": "Fly", "tags": ["high"]},
            ]
        },
    }

    with (tmp_path / "sample.yaml").open("w", encoding="utf-8") as fh:
        json.dump(content, fh)


def _new_state() -> FSMContext:
    storage = MemoryStorage()
    return FSMContext(storage=storage, key=StorageKey(bot_id=99, chat_id=777, user_id=555))


@pytest.mark.asyncio
async def test_quiz_flow_smoke(monkeypatch, tmp_path, tmp_path_factory, **_extra):  # noqa: ARG001 - fixture compatibility
    quiz_engine.load_quiz.cache_clear()
    original_hooks = dict(quiz_engine.QUIZ_HOOKS)
    quiz_engine.QUIZ_HOOKS.clear()
    monkeypatch.setattr(quiz_engine, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(quiz_engine, "session_scope", _dummy_scope)
    monkeypatch.setattr(quiz_engine.events_repo, "log", AsyncMock())
    monkeypatch.setattr(quiz_engine, "commit_safely", AsyncMock())
    monkeypatch.setattr(quiz_engine, "ai_tip_for_quiz", AsyncMock(return_value=None))

    _write_quiz(tmp_path)

    state = _new_state()
    entry_message = DummyMessage()

    try:
        await start_quiz(entry_message, state, "sample")
        definition = load_quiz("sample")

        question_message = entry_message.children[-1]

        for index, question in enumerate(definition.questions):
            callback_data = build_answer_callback_data("sample", question.id, question.options[0].key)
            callback = DummyCallback(callback_data, question_message, user_id=555)
            await answer_callback(callback, state)
            if index < len(definition.questions) - 1:
                question_message = question_message.children[-1]

        assert await state.get_state() is None
    finally:
        await state.storage.close()
        quiz_engine.QUIZ_HOOKS.clear()
        quiz_engine.QUIZ_HOOKS.update(original_hooks)
        quiz_engine.load_quiz.cache_clear()
