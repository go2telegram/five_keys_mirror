from __future__ import annotations

import logging
from importlib import reload

import pytest

from app.config import settings
from app.handlers import health as health_module

if not settings.DEBUG_COMMANDS:
    settings.DEBUG_COMMANDS = True
    health_module = reload(health_module)


@pytest.mark.anyio("asyncio")
async def test_ping_logs(caplog: pytest.LogCaptureFixture) -> None:
    if not health_module.settings.DEBUG_COMMANDS:
        pytest.skip("debug commands disabled")

    message = type(
        "MessageStub",
        (),
        {
            "from_user": type("User", (), {"id": 1, "username": "tester"})(),
            "answers": [],
            "answer": None,
        },
    )()

    async def _answer(self, text):
        self.answers.append(text)

    message.answer = _answer.__get__(message, message.__class__)

    with caplog.at_level(logging.INFO, logger="health"):
        await health_module.ping(message)  # type: ignore[arg-type]

    assert any("PING ok" in record.message for record in caplog.records)
    assert any("pong" in text for text in message.answers)
