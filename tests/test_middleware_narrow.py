"""Tests for AuditMiddleware when registered on narrow update types."""

from __future__ import annotations

import datetime as dt
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares import AuditMiddleware, CallbackTraceMiddleware, set_callback_trace_enabled


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
    assert any("MSG update=None msg_id=10" in record.message for record in caplog.records)


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
    assert any(
        "CB  update=None msg_id=20 cb_id=cb-1" in record.message for record in caplog.records
    )


@pytest.mark.anyio("asyncio")
async def test_callback_trace_logs_handler(caplog: pytest.LogCaptureFixture) -> None:
    middleware = CallbackTraceMiddleware()
    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=77, chat_id=300, user_id=501))
    await state.set_state("quiz:before")

    async def handler(event: CallbackQuery, data: dict) -> str:
        await state.set_state("quiz:after")
        return "ok"

    message = Message.model_construct(
        message_id=42,
        date=dt.datetime.utcnow(),
        chat=Chat(id=300, type="private"),
        from_user=User(id=501, is_bot=False, first_name="Trace"),
    )
    callback = CallbackQuery.model_construct(
        id="cb-trace",
        from_user=User(id=501, is_bot=False, first_name="Trace"),
        data="quiz:energy:nav:next",
        chat_instance="trace",
        message=message,
    )

    set_callback_trace_enabled(True)
    try:
        with caplog.at_level(logging.INFO, logger="callback.trace"):
            await middleware(
                handler,
                callback,
                {"state": state, "event_router": SimpleNamespace(name="quiz")},
            )
    finally:
        set_callback_trace_enabled(False)
        await storage.close()

    records = [record.message for record in caplog.records if record.name == "callback.trace"]
    assert any("handler=" in record for record in records)
    assert any("state_before=quiz:before" in record for record in records)
    assert any("state_after=quiz:after" in record for record in records)
