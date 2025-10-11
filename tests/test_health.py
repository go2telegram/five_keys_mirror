from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from importlib import reload

import pytest
from aiogram.types import User

from app.config import settings
from app.handlers import health as health_module

if not settings.DEBUG_COMMANDS:
    settings.DEBUG_COMMANDS = True
    health = reload(health_module)
else:
    health = health_module


class DummyMessage:
    def __init__(self) -> None:
        self.from_user = User(id=1, is_bot=False, first_name="Tester", username="tester")
        self.answers: list[str] = []
        self.bot = None

    async def answer(self, text: str) -> None:  # noqa: ANN001
        self.answers.append(text)


@pytest.mark.anyio("asyncio")
async def test_ping_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    message = DummyMessage()
    await health.ping(message)  # type: ignore[arg-type]
    assert any("pong" in text for text in message.answers)


class _Webhook:
    def __init__(self) -> None:
        self.url = "https://example.test/webhook"
        self.pending_update_count = 2


@pytest.mark.anyio("asyncio")
async def test_doctor_report(monkeypatch: pytest.MonkeyPatch) -> None:
    message = DummyMessage()

    async def fake_get_webhook_info():  # noqa: ANN202
        return _Webhook()

    message.bot = type("Bot", (), {"get_webhook_info": fake_get_webhook_info})()

    @asynccontextmanager
    async def fake_session_scope():  # noqa: ANN202
        yield object()

    class _Event:
        def __init__(self, name: str) -> None:
            self.name = name
            self.ts = datetime(2024, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(health, "session_scope", fake_session_scope)
    monkeypatch.setattr(health.events_repo, "recent_events", lambda *_args, **_kwargs: [_Event("plan_generated")])

    await health.doctor(message)  # type: ignore[arg-type]
    joined = "\n".join(message.answers)
    assert "Doctor report:" in joined
    assert "Build" in joined
    assert "version" in joined
    assert "commit" in joined
    assert "time" in joined
    assert "plan_generated" in joined
