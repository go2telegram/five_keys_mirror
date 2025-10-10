from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RateLimitMiddleware(default_limit=(2, 30.0))

    handler = AsyncMock(return_value="ok")
    message = Message.model_validate(
        {
            "message_id": 1,
            "date": datetime.utcnow(),
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "is_bot": False, "first_name": "User", "username": "user"},
            "text": "hello",
        }
    )

    answer_mock = AsyncMock(return_value=None)

    async def fake_answer(self, *args, **kwargs):
        return await answer_mock(*args, **kwargs)

    monkeypatch.setattr(Message, "answer", fake_answer, raising=False)

    assert await middleware(handler, message, {}) == "ok"
    assert await middleware(handler, message, {}) == "ok"
    assert handler.await_count == 2

    result = await middleware(handler, message, {})
    assert result is None
    handler.assert_awaited()
    assert handler.await_count == 2
    answer_mock.assert_awaited_once()
    assert "Слишком много запросов" in answer_mock.call_args.args[0]


@pytest.mark.asyncio
async def test_rate_limit_blocks_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = RateLimitMiddleware(default_limit=(1, 60.0))

    handler = AsyncMock(return_value=None)
    chat = Chat(id=321, type="private")
    user = User(id=555, is_bot=False, first_name="Tester", username="tester")
    callback = CallbackQuery.model_validate(
        {
            "id": "cb1",
            "from": user.model_dump(mode="json"),
            "chat_instance": "ci",
            "data": "test",
            "message": Message.model_validate(
                {
                    "message_id": 5,
                    "date": datetime.utcnow(),
                    "chat": chat.model_dump(mode="json"),
                    "from": user.model_dump(mode="json"),
                    "text": "payload",
                }
            ).model_dump(mode="json"),
        }
    )
    answer_mock = AsyncMock(return_value=True)

    async def fake_answer(self, *args, **kwargs):
        return await answer_mock(*args, **kwargs)

    monkeypatch.setattr(CallbackQuery, "answer", fake_answer, raising=False)

    await middleware(handler, callback, {})
    handler.assert_awaited_once()

    result = await middleware(handler, callback, {})
    assert result is None
    assert handler.await_count == 1
    answer_mock.assert_awaited_once()
    args, kwargs = answer_mock.call_args
    assert "Слишком много запросов" in args[0]
    assert kwargs.get("show_alert") is True
