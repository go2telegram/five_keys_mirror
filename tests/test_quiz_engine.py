"""Unit tests for the generic quiz engine."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

if "yaml" not in sys.modules:  # pragma: no cover - test environment bootstrap
    yaml_stub = types.ModuleType("yaml")

    def _missing_safe_load(_stream):  # noqa: D401 - minimal stub
        raise RuntimeError("PyYAML is not available in tests")

    yaml_stub.safe_load = _missing_safe_load
    sys.modules["yaml"] = yaml_stub

from app.quiz import engine


class DummyMessage:
    """A lightweight stand-in for aiogram's Message object."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.reply_markup_history: list[object | None] = []
        self.deleted = False

    async def answer_photo(self, photo, caption, reply_markup=None):  # noqa: ANN001
        self.sent.append(("photo", photo, caption))
        self.reply_markup_history.append(reply_markup)
        return self

    async def answer(self, text, reply_markup=None):  # noqa: ANN001
        self.sent.append(("text", text, None))
        self.reply_markup_history.append(reply_markup)
        return self

    async def delete(self) -> None:
        self.deleted = True


class DummyCallback:
    """Minimal callback query surrogate."""

    def __init__(self, message: DummyMessage, data: str, *, user_id: int = 42) -> None:
        self.message = message
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self._answers: list[str | None] = []

    async def answer(self, text: str | None = None) -> None:
        self._answers.append(text)


async def _make_state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=200)
    return FSMContext(storage=storage, key=key)


def _make_energy_definition() -> engine.QuizDefinition:
    questions: list[engine.QuizQuestion] = []
    for idx in range(5):
        options = [
            engine.QuizOption(key="a", text=f"Answer A{idx}", score=1, tags=[f"tag{idx}a"]),
            engine.QuizOption(key="b", text=f"Answer B{idx}", score=2, tags=[f"tag{idx}b"]),
            engine.QuizOption(key="c", text=f"Answer C{idx}", score=3, tags=[f"tag{idx}c"]),
        ]
        questions.append(
            engine.QuizQuestion(
                id=f"q{idx + 1}",
                text=f"Question {idx + 1}",
                options=options,
                image=f"energy/q{idx + 1}.png",
            )
        )

    thresholds = [
        engine.QuizThreshold(min=0, max=7, label="Low", advice="Keep working", tags=["tag"]),
        engine.QuizThreshold(min=8, max=15, label="High", advice="Great!", tags=["tag2"]),
    ]

    return engine.QuizDefinition(
        name="energy",
        title="Energy",
        questions=questions,
        thresholds=thresholds,
        cover="energy/cover.png",
    )


def _patch_loader(monkeypatch: pytest.MonkeyPatch, *definitions: engine.QuizDefinition) -> None:
    mapping = {definition.name: definition for definition in definitions}

    def _fake_load(name: str) -> engine.QuizDefinition:
        try:
            return mapping[name]
        except KeyError as exc:  # pragma: no cover - guard rail
            raise FileNotFoundError(name) from exc

    monkeypatch.setattr(engine, "load_quiz", _fake_load)


@pytest.mark.asyncio
async def test_quiz_engine_happy_path(monkeypatch):
    definition = _make_energy_definition()
    _patch_loader(monkeypatch, definition)

    message = DummyMessage()
    state = await _make_state()

    recorded: list[tuple[int, int, tuple[str, ...]]] = []

    async def _on_finish(user_id, definition, result):  # noqa: ANN001
        assert result.source is not None
        recorded.append((user_id, result.total_score, tuple(result.collected_tags)))

    engine.register_quiz_hooks(definition.name, engine.QuizHooks(on_finish=_on_finish))

    try:
        await engine.start_quiz(message, state, definition.name)
        assert await state.get_state() == engine.QuizSession.Q1.state
        assert message.sent[0][0] == "photo"
        assert message.sent[0][1].startswith(engine.QUIZ_REMOTE_BASE)

        for idx, question in enumerate(definition.questions):
            callback = DummyCallback(message, f"tests:answer:{definition.name}:{idx}:0")
            await engine.answer_callback(callback, state)

        assert await state.get_state() is None
        assert message.sent[-1][0] == "text"
        assert recorded and recorded[0][0] == 42
        assert recorded[0][1] == sum(opt.score for opt in (q.options[0] for q in definition.questions))
    finally:
        engine.QUIZ_HOOKS.pop(definition.name, None)
        await state.storage.close()


@pytest.mark.asyncio
async def test_quiz_engine_without_images(monkeypatch, caplog, request):  # noqa: ARG001
    options = [
        engine.QuizOption(key="a", text="A", score=1, tags=["t1"]),
        engine.QuizOption(key="b", text="B", score=2, tags=["t2"]),
    ]
    questions = [
        engine.QuizQuestion(id=f"q{i}", text=f"Question {i}", options=list(options), image=None)
        for i in range(1, 6)
    ]
    thresholds = [
        engine.QuizThreshold(min=0, max=10, label="OK", advice="Keep going", tags=["t1"]),
    ]
    dummy_definition = engine.QuizDefinition(
        name="dummy",
        title="Dummy",
        questions=questions,
        thresholds=thresholds,
    )

    _patch_loader(monkeypatch, dummy_definition)

    message = DummyMessage()
    state = await _make_state()

    with caplog.at_level("WARNING"):
        await engine.start_quiz(message, state, dummy_definition.name)

    assert any("falling back to text" in rec.message for rec in caplog.records)
    assert message.sent[0][0] == "text"

    await state.storage.close()


@pytest.mark.asyncio
async def test_quiz_engine_back_button(monkeypatch):
    definition = _make_energy_definition()
    _patch_loader(monkeypatch, definition)

    message = DummyMessage()
    state = await _make_state()

    await engine.start_quiz(message, state, definition.name)

    first_answer = DummyCallback(message, f"tests:answer:{definition.name}:0:0")
    await engine.answer_callback(first_answer, state)

    assert await state.get_state() == engine.QuizSession.Q2.state
    data = await state.get_data()
    assert data["index"] == 1

    back_call = DummyCallback(message, f"tests:back:{definition.name}:1")
    await engine.answer_callback(back_call, state)

    assert await state.get_state() == engine.QuizSession.Q1.state
    data = await state.get_data()
    assert data["index"] == 0
    assert data["answers"]["q1"] == "a"

    new_answer = DummyCallback(message, f"tests:answer:{definition.name}:0:2")
    await engine.answer_callback(new_answer, state)
    data = await state.get_data()
    assert data["score"] == 3
    assert await state.get_state() == engine.QuizSession.Q2.state

    await state.storage.close()
