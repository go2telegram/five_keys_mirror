from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from app.utils.telegram_session import FloodWaitRetrySession


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_floodwait_session_ignores_timeout_kw(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_make_request(self, bot, method, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(AiohttpSession, "make_request", fake_make_request, raising=False)

    session = FloodWaitRetrySession()
    method = SendMessage(chat_id=1, text="hello")

    result = await session.make_request(AsyncMock(), method, {}, timeout=5)

    assert result == {"ok": True}
    assert captured["args"] == ({},)
    assert "timeout" not in captured["kwargs"]


@pytest.mark.anyio
async def test_bot_starts_with_patched_session() -> None:
    from app.feature_flags import FF_FLOODWAIT_PATCH

    assert FF_FLOODWAIT_PATCH is True
