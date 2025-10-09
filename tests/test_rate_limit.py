from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock

import pytest
from aiogram import types

from app.middlewares.rate_limit import RateLimitMiddleware


def _make_message(user_id: int, text: str) -> types.Message:
    return types.Message.model_construct(
        message_id=1,
        date=dt.datetime.now(dt.timezone.utc),
        chat=types.Chat.model_construct(id=user_id, type="private"),
        from_user=types.User.model_construct(id=user_id, is_bot=False, first_name="Test"),
        text=text,
    )


@pytest.mark.anyio("asyncio")
async def test_rate_limit_blocks_after_threshold() -> None:
    middleware = RateLimitMiddleware(default_limit=2, interval_seconds=60.0)
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    message = _make_message(42, "hello")

    calls = 0

    async def handler(event: types.TelegramObject, _: dict) -> None:
        nonlocal calls
        calls += 1

    for _ in range(2):
        await middleware(handler, message, {"bot": bot})

    result = await middleware(handler, message, {"bot": bot})
    assert result is None
    assert calls == 2
    assert bot.send_message.await_count == 1


@pytest.mark.anyio("asyncio")
async def test_rate_limit_command_specific() -> None:
    middleware = RateLimitMiddleware(
        default_limit=10,
        interval_seconds=60.0,
        command_limits={"recommend": (1, 30.0)},
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    message = _make_message(77, "/recommend")

    async def handler(event: types.TelegramObject, _: dict) -> None:
        return None

    await middleware(handler, message, {"bot": bot})
    result = await middleware(handler, message, {"bot": bot})
    assert result is None
    assert bot.send_message.await_count == 1
