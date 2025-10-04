"""Tests for the audit middleware logging behaviour."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares.audit import AuditMiddleware


def test_audit_logs_message(caplog) -> None:
    middleware = AuditMiddleware()
    caplog.set_level(logging.INFO, logger="audit")

    message = Message.model_validate(
        {
            "message_id": 1,
            "date": datetime.utcnow(),
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "is_bot": False, "first_name": "User", "username": "user"},
            "text": "hello",
        }
    )

    handler = AsyncMock(return_value="ok")

    result = asyncio.run(middleware(handler, message, {}))

    assert result == "ok"
    handler.assert_awaited()
    assert "MSG uid=200" in caplog.text


def test_audit_logs_callback_and_errors(caplog) -> None:
    middleware = AuditMiddleware()
    caplog.set_level(logging.INFO, logger="audit")

    chat = Chat(id=321, type="private")
    sender = User(id=654, is_bot=False, first_name="Tester", username="tester")

    callback = CallbackQuery.model_validate(
        {
            "id": "abc",
            "from": sender.model_dump(mode="json"),
            "chat_instance": "ci",
            "data": "cb:data",
            "message": Message.model_validate(
                {
                    "message_id": 5,
                    "date": datetime.utcnow(),
                    "chat": chat.model_dump(mode="json"),
                    "from": sender.model_dump(mode="json"),
                    "text": "payload",
                }
            ).model_dump(mode="json"),
        }
    )

    handler = AsyncMock(return_value=None)
    asyncio.run(middleware(handler, callback, {}))
    assert "CB  uid=654" in caplog.text

    failing = AsyncMock(side_effect=RuntimeError("boom"))
    caplog.clear()
    with pytest.raises(RuntimeError):
        asyncio.run(middleware(failing, callback, {}))
    assert "Handler error on event" in caplog.text
