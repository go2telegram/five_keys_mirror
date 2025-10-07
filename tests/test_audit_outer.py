"""Tests for the audit middleware registered as outer middleware."""

from __future__ import annotations

import datetime as dt
import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.middlewares import AuditMiddleware


@pytest.mark.anyio("asyncio")
async def test_audit_logs_update_message(caplog: pytest.LogCaptureFixture) -> None:
    middleware = AuditMiddleware()
    handler = AsyncMock()

    message = Message.model_construct(
        message_id=1,
        date=dt.datetime.utcnow(),
        chat=Chat(id=100, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Test", username="tester"),
        text="hello",
    )
    update = Update.model_construct(update_id=1, message=message)

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, update, {})

    handler.assert_awaited()
    assert any("UPD kind=Update update_id=1" in record.message for record in caplog.records)
    assert any("MSG update=1 msg_id=1" in record.message for record in caplog.records)


@pytest.mark.anyio("asyncio")
async def test_audit_logs_update_callback(caplog: pytest.LogCaptureFixture) -> None:
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
    update = Update.model_construct(update_id=2, callback_query=callback)

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, update, {})

    handler.assert_awaited()
    assert any("UPD kind=Update update_id=2" in record.message for record in caplog.records)
    assert any("CB  update=2 msg_id=2 cb_id=1" in record.message for record in caplog.records)
