import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.quiz import engine as quiz_engine, handlers as quiz_handlers
from app.quiz.engine import (
    QuizHooks,
    build_answer_callback_data,
    build_nav_callback_data,
    load_quiz,
)


class FakeMessage:
    _next_id = 0

    def __init__(self, chat_id: int = 9001):
        type(self)._next_id += 1
        self.message_id = type(self)._next_id
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=4242, language_code="ru")
        self.answers: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []
        self.last_child: "FakeMessage" | None = None
        self.text: str | None = None
        self.caption: str | None = None
        self.reply_markup = None
        self.deleted = False

    async def answer(self, text: str, reply_markup=None):
        child = FakeMessage(self.chat.id)
        child.text = text
        child.reply_markup = reply_markup
        self.answers.append({"text": text, "reply_markup": reply_markup, "message": child})
        self.last_child = child
        return child

    async def answer_photo(self, photo, caption: str, reply_markup=None):
        child = FakeMessage(self.chat.id)
        child.photo = photo
        child.caption = caption
        child.reply_markup = reply_markup
        self.photos.append(
            {"photo": photo, "caption": caption, "reply_markup": reply_markup, "message": child}
        )
        self.last_child = child
        return child

    async def delete(self):
        self.deleted = True


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=4242, username="energy_tester")
        self._answers: list[dict[str, object]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self._answers.append({"text": text, "show_alert": show_alert})


def _markup_to_snapshot(markup) -> str:
    if markup is None:
        return "{}"
    data = markup.model_dump()
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _read_snapshot(name: str) -> str:
    path = Path(__file__).parent / "snapshots" / f"{name}.json"
    return path.read_text(encoding="utf-8").strip()


@pytest.mark.asyncio
async def test_energy_quiz_flow(monkeypatch):
    monkeypatch.setattr("app.quiz.engine.ai_tip_for_quiz", AsyncMock(return_value=None))

    from app.handlers import quiz_energy as energy_handlers

    call_order: list[str] = []

    async def record_cards(*args, **kwargs):
        call_order.append("cards")

    async def record_cta(*args, **kwargs):
        call_order.append("cta")

    cards_mock = AsyncMock(side_effect=record_cards)
    cta_mock = AsyncMock(side_effect=record_cta)
    monkeypatch.setattr(energy_handlers, "send_product_cards", cards_mock)
    monkeypatch.setattr(energy_handlers, "send_premium_cta", cta_mock)

    async def fake_on_finish(user_id, definition, result):
        origin = result.origin
        if not origin:
            return False
        await energy_handlers.send_product_cards(origin, "Итог", [])
        await energy_handlers.send_premium_cta(
            origin,
            "🔓 Еженедельные обновления доступны в Премиум",
            source="quiz:energy",
        )
        return False

    monkeypatch.setitem(quiz_engine.QUIZ_HOOKS, "energy", QuizHooks(on_finish=fake_on_finish))

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=77, chat_id=9001, user_id=4242))

    try:
        root_message = FakeMessage()
        await quiz_handlers.command_tests(root_message)

        menu_message = root_message.last_child
        assert menu_message is not None, "menu message must be created"

        menu_markup = menu_message.reply_markup
        energy_target = build_nav_callback_data("energy", "next")
        energy_button = None
        for row in menu_markup.inline_keyboard:
            for button in row:
                if button.callback_data == energy_target:
                    energy_button = button
                    break
            if energy_button:
                break

        assert energy_button is not None, "energy quiz button not found"

        start_call = FakeCallback(energy_button.callback_data, menu_message)
        await quiz_handlers.quiz_callbacks(start_call, state)

        definition = load_quiz("energy")
        question_message = menu_message.last_child
        assert question_message is not None, "first question message is missing"

        snapshots: list[str] = []
        for idx, question in enumerate(definition.questions):
            markup_dump = _markup_to_snapshot(question_message.reply_markup)
            snapshots.append(markup_dump)

            answer_data = build_answer_callback_data(
                "energy", question.id, question.options[-1].key
            )
            answer_call = FakeCallback(answer_data, question_message)
            await quiz_handlers.quiz_callbacks(answer_call, state)

            if idx < len(definition.questions) - 1:
                question_message = question_message.last_child
                assert question_message is not None, f"question message {idx + 2} should exist"
            else:
                # The last question should produce a result message and clear the state.
                result_message = question_message.answers[-1]["message"]
                final_text = question_message.answers[-1]["text"]
                assert "score:" in final_text
                assert "label:" in final_text
                assert result_message.deleted is False

        assert await state.get_state() is None

        for idx, dump in enumerate(snapshots, start=1):
            expected = _read_snapshot(f"energy_question_{idx}")
            assert dump == expected

        assert call_order == ["cards", "cta"]
        assert cards_mock.await_count == 1
        assert cta_mock.await_count == 1
    finally:
        await storage.close()
