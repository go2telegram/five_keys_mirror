"""Tests for the audit middleware registered as outer middleware."""

from __future__ import annotations

import datetime as dt
import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares import AuditMiddleware


@pytest.mark.anyio("asyncio")
async def test_audit_logs_message(caplog: pytest.LogCaptureFixture) -> None:
    middleware = AuditMiddleware()
    handler = AsyncMock()

    message = Message.model_construct(
        message_id=1,
        date=dt.datetime.utcnow(),
        chat=Chat(id=100, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Test", username="tester"),
        text="hello",
    )

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, message, {})

    handler.assert_awaited()
    assert any("MSG uid=42" in record.message for record in caplog.records)


@pytest.mark.anyio("asyncio")
async def test_audit_logs_callback(caplog: pytest.LogCaptureFixture) -> None:
    middleware = AuditMiddleware()
    handler = AsyncMock()

    message = Message.model_construct(
        message_id=2,
        date=dt.datetime.utcnow(),
        chat=Chat(id=101, type="private"),
        from_user=User(id=77, is_bot=False, first_name="Call", username="caller"),
    )
    callback = CallbackQuery.model_construct(
        id="1",
        from_user=User(id=77, is_bot=False, first_name="Call", username="caller"),
        data="test:data",
        chat_instance="ci",
        message=message,
    )

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, callback, {})

    handler.assert_awaited()
    assert any("CB  uid=77" in record.message for record in caplog.records)
