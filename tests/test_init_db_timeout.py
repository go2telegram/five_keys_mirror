from __future__ import annotations

import asyncio
import logging

import pytest

from app.db import session as session_module


@pytest.mark.anyio
async def test_init_db_handles_timeout(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:  # noqa: ANN001
    class _FakeAwaitable:
        def __await__(self):  # noqa: D401 - helper inside test
            async def _stall() -> None:
                await asyncio.sleep(0)

            return _stall().__await__()

        def close(self) -> None:  # noqa: D401 - helper inside test
            return None

    async def fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, D401 - helper inside test
        if func is session_module._alembic_upgrade_head_sync:
            return _FakeAwaitable()
        if func is session_module._fetch_revision_sync:
            return "rev-test"
        return None

    async def fake_wait_for(awaitable, timeout):  # noqa: ANN001, D401 - helper inside test
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(session_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(session_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(session_module, "async_engine", None)

    with caplog.at_level(logging.INFO, logger="db"):
        revision = await session_module.init_db(engine=None)

    assert revision == "rev-test"
    messages = [record.message for record in caplog.records if record.name == "db"]
    assert any("migration timeout" in message for message in messages)
