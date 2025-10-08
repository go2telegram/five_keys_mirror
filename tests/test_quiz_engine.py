import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage


def _install_yaml_stub() -> None:
    if "yaml" in sys.modules:
        return

    class _YamlStub:
        @staticmethod
        def safe_load(stream):
            data = stream.read() if hasattr(stream, "read") else stream
            return json.loads(data)

        @staticmethod
        def safe_dump(data, stream, allow_unicode=False, **kwargs):
            json.dump(data, stream)

    sys.modules["yaml"] = _YamlStub()


_install_yaml_stub()

from app.quiz import engine
from app.quiz.engine import QuizHooks, register_quiz_hooks, start_quiz, answer_callback, back_callback


class DummyMessage:
    def __init__(self):
        self.children = []
        self.text = None
        self.caption = None
        self.photo = None
        self.reply_markup = None
        self.deleted = False
        self.actions = []

    async def answer(self, text: str, reply_markup=None):
        child = DummyMessage()
        child.text = text
        child.reply_markup = reply_markup
        self.children.append(child)
        return child

    async def answer_photo(self, photo, caption: str, reply_markup=None):
        child = DummyMessage()
        child.photo = photo
        child.caption = caption
        child.reply_markup = reply_markup
        self.children.append(child)
        return child

    async def delete(self):
        self.deleted = True

    async def answer_chat_action(self, action: str):
        self.actions.append(action)


class DummyCallback:
    def __init__(self, data: str, message: DummyMessage, user_id: int = 1, username: str | None = "tester"):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.answers = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append((text, show_alert))


@pytest.fixture
def quiz_tmp(tmp_path, monkeypatch):
    engine.load_quiz.cache_clear()
    original_hooks = dict(engine.QUIZ_HOOKS)
    engine.QUIZ_HOOKS.clear()
    monkeypatch.setattr(engine, "DATA_ROOT", tmp_path)
    try:
        yield tmp_path
    finally:
        engine.QUIZ_HOOKS.clear()
        engine.QUIZ_HOOKS.update(original_hooks)


def _write_quiz(tmp_path, name="sample", *, with_images=True):
    questions = []
    for idx in range(5):
        question = {
            "id": f"q{idx+1}",
            "text": f"Question {idx+1}?",
            "options": [
                {"key": "a", "text": "A", "score": 1, "tags": [f"tag{idx+1}"]},
                {"key": "b", "text": "B", "score": 2, "tags": [f"tag{idx+1}"]},
            ],
            "hint": f"Hint {idx+1}",
        }
        if with_images:
            question["image"] = f"folder/q{idx+1}.png"
        questions.append(question)

    content = {
        "title": "Sample Quiz",
        **({"cover": "folder/cover.png"} if with_images else {}),
        "questions": questions,
        "result": {
            "thresholds": [
                {"min": 0, "max": 5, "label": "Low", "advice": "Rest"},
                {"min": 6, "max": 10, "label": "Mid", "advice": "Keep going"},
                {"min": 11, "max": 15, "label": "High", "advice": "Great"},
            ]
        },
    }

    with (tmp_path / f"{name}.yaml").open("w", encoding="utf-8") as fh:
        json.dump(content, fh)


def _new_state() -> FSMContext:
    storage = MemoryStorage()
    return FSMContext(storage=storage, key=StorageKey(bot_id=99, chat_id=777, user_id=555))


def _run(coro):
    return asyncio.run(coro)


def test_quiz_happy_path(monkeypatch, quiz_tmp):
    async def _test():
        _write_quiz(quiz_tmp)
        hook_calls = []

        store_mock = AsyncMock()
        monkeypatch.setattr(engine, "_store_quiz_result", store_mock)

        async def _on_finish(user_id, definition, result):
            hook_calls.append((user_id, definition.name, result.total_score, tuple(sorted(result.collected_tags))))
            return False

        register_quiz_hooks("sample", QuizHooks(on_finish=_on_finish))

        state = _new_state()
        try:
            entry_message = DummyMessage()
            await start_quiz(entry_message, state, "sample")

            state_data = await state.get_data()
            assert state_data["index"] == 0
            current_state = await state.get_state()
            assert current_state and current_state.endswith("QuizSession:Q1")

            current_message = entry_message.children[-1]

            for idx in range(5):
                callback = DummyCallback(f"tests:answer:sample:{idx}:0", current_message)
                await answer_callback(callback, state)
                if idx < 4:
                    current_message = current_message.children[-1]

            assert await state.get_state() is None
            assert hook_calls == [(callback.from_user.id, "sample", 5, ("tag1", "tag2", "tag3", "tag4", "tag5"))]
            store_mock.assert_awaited()
        finally:
            await state.storage.close()

    _run(_test())


def test_quiz_without_images(monkeypatch, quiz_tmp):
    async def _test():
        _write_quiz(quiz_tmp, with_images=False)
        state = _new_state()
        try:
            entry_message = DummyMessage()
            await start_quiz(entry_message, state, "sample")

            question_message = entry_message.children[-1]
            assert "Вопрос 1/5" in question_message.text
            assert "Hint 1" in question_message.text
            assert engine.DEFAULT_HINT not in question_message.text
        finally:
            await state.storage.close()

    _run(_test())


def test_quiz_back_navigation(monkeypatch, quiz_tmp):
    async def _test():
        _write_quiz(quiz_tmp)
        state = _new_state()
        try:
            entry_message = DummyMessage()
            await start_quiz(entry_message, state, "sample")

            current_message = entry_message.children[-1]

            first_callback = DummyCallback("tests:answer:sample:0:0", current_message)
            await answer_callback(first_callback, state)
            state_data = await state.get_data()
            assert state_data["index"] == 1
            assert state_data["score"] == 1

            current_message = current_message.children[-1]
            back_call = DummyCallback("tests:back:sample:1", current_message)
            await back_callback(back_call, state)

            state_data = await state.get_data()
            assert state_data["index"] == 0
            assert state_data["score"] == 0
            current_state = await state.get_state()
            assert current_state and current_state.endswith("QuizSession:Q1")
        finally:
            await state.storage.close()

    _run(_test())
