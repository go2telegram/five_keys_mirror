"""Tests for AuditMiddleware when registered on narrow update types."""

from __future__ import annotations

import datetime as dt
import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares import AuditMiddleware


@pytest.mark.anyio("asyncio")
async def test_audit_logs_message_direct(caplog: pytest.LogCaptureFixture) -> None:
    middleware = AuditMiddleware()
    handler = AsyncMock()

    message = Message.model_construct(
        message_id=10,
        date=dt.datetime.utcnow(),
        chat=Chat(id=200, type="private"),
        from_user=User(id=12, is_bot=False, first_name="Foo", username="foo"),
        text="hi",
    )

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, message, {})

    handler.assert_awaited()
    assert any("MSG update=None message=10" in record.message for record in caplog.records)


@pytest.mark.anyio("asyncio")
async def test_audit_logs_callback_direct(caplog: pytest.LogCaptureFixture) -> None:
    middleware = AuditMiddleware()
    handler = AsyncMock()

    message = Message.model_construct(
        message_id=20,
        date=dt.datetime.utcnow(),
        chat=Chat(id=201, type="private"),
        from_user=User(id=55, is_bot=False, first_name="Bar", username="bar"),
    )
    callback = CallbackQuery.model_construct(
        id="cb-1",
        from_user=User(id=55, is_bot=False, first_name="Bar", username="bar"),
        data="demo:data",
        chat_instance="ci",
        message=message,
    )

    with caplog.at_level(logging.INFO, logger="audit"):
        await middleware(handler, callback, {})

    handler.assert_awaited()
    assert any("CB  update=None message=20" in record.message for record in caplog.records)
