from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("yaml")

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.quiz.engine import answer_callback, build_answer_callback_data, load_quiz, start_quiz


class _DummyMessage:
    _next_id = 0

    def __init__(self, chat_id: int = 1001):
        type(self)._next_id += 1
        self.message_id = type(self)._next_id
        self.chat = SimpleNamespace(id=chat_id)
        self.answers: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []
        self.last_child: _DummyMessage | None = None
        self.deleted = False

    async def answer(self, text: str, **kwargs) -> "_DummyMessage":  # noqa: ANN003
        self.answers.append({"text": text, "kwargs": kwargs})
        child = _DummyMessage(self.chat.id)
        self.last_child = child
        return child

    async def answer_photo(
        self, photo: str, caption: str, **kwargs
    ) -> "_DummyMessage":  # noqa: ANN003
        self.photos.append({"photo": photo, "caption": caption, "kwargs": kwargs})
        child = _DummyMessage(self.chat.id)
        self.last_child = child
        return child

    async def delete(self) -> None:
        self.deleted = True


class _DummyCallback:
    def __init__(self, message: _DummyMessage):
        self.message = message
        self.from_user = SimpleNamespace(id=4242, username="sleep_tester")
        self.data = ""
        self.answered: list[dict[str, object]] = []

    async def answer(self, text: str | None = None, *, show_alert: bool | None = None) -> None:
        self.answered.append({"text": text, "show_alert": show_alert})


@pytest.mark.asyncio
async def test_quiz_sleep_yaml_flow():
    definition = load_quiz("sleep")
    storage = MemoryStorage()
    state = FSMContext(storage, StorageKey(bot_id=99, chat_id=555, user_id=4242))

    root_message = _DummyMessage()
    await start_quiz(root_message, state, "sleep")

    current_message = root_message.last_child
    assert current_message is not None, "quiz must send the first question"

    for idx, question in enumerate(definition.questions):
        call = _DummyCallback(current_message)
        call.data = build_answer_callback_data("sleep", question.id, question.options[-1].key)
        await answer_callback(call, state)

        if idx < len(definition.questions) - 1:
            current_message = current_message.last_child
            assert current_message is not None, "next question message is missing"
        else:
            result_texts = [entry["text"] for entry in current_message.answers]
            assert result_texts, "expected at least one result message"
            final_text = result_texts[-1]
            for fragment in ("score:", "label:", "advice:", "tags:"):
                assert fragment in final_text
            for tag in ("sleep_support", "sleep_calm", "magnesium", "glycine", "mct"):
                assert tag in final_text
            assert current_message.deleted

    assert await state.get_state() is None
