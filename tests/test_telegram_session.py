from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from app.utils.telegram_session import FloodWaitRetrySession


@pytest.mark.asyncio
async def test_flood_wait_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    async def fake_make_request(self, bot, method, data):
        attempts.append(1)
        if len(attempts) < 3:
            raise TelegramRetryAfter(method, "Flood", retry_after=2)
        return {"ok": True}

    monkeypatch.setattr(AiohttpSession, "make_request", fake_make_request, raising=False)

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    session = FloodWaitRetrySession(max_attempts=4, sleep_func=fake_sleep)
    method = SendMessage(chat_id=1, text="hello")

    result = await session.make_request(AsyncMock(), method, {})

    assert result == {"ok": True}
    assert len(attempts) == 3
    assert sleeps == [2.0, 2.0]


@pytest.mark.asyncio
async def test_flood_wait_gives_up_after_max(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_make_request(self, bot, method, data):
        raise TelegramRetryAfter(method, "Flood", retry_after=1)

    monkeypatch.setattr(AiohttpSession, "make_request", fake_make_request, raising=False)

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    session = FloodWaitRetrySession(max_attempts=2, sleep_func=fake_sleep)
    method = SendMessage(chat_id=42, text="ping")

    with pytest.raises(TelegramRetryAfter):
        await session.make_request(AsyncMock(), method, {})

    assert sleeps == [1.0]
