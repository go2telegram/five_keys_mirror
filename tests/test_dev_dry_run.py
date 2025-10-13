from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import main as app_main


@pytest.mark.asyncio
async def test_dev_dry_run_skips_bot_initialization(monkeypatch):
    """When DEV_DRY_RUN is enabled the Telegram stack must not be created."""

    monkeypatch.setattr(app_main.settings, "DEV_DRY_RUN", True, raising=False)
    monkeypatch.setattr(app_main.settings, "BOT_TOKEN", "", raising=False)

    init_db_mock = AsyncMock(return_value="rev-test")
    monkeypatch.setattr(app_main, "init_db", init_db_mock)

    runner = SimpleNamespace(cleanup=AsyncMock(name="cleanup"))
    site = SimpleNamespace(stop=AsyncMock(name="stop"))
    setup_service_mock = AsyncMock(return_value=(runner, site))
    monkeypatch.setattr(app_main, "_setup_service_app", setup_service_mock)

    wait_mock = AsyncMock(name="wait_forever")
    monkeypatch.setattr(app_main, "_wait_forever", wait_mock)

    cleanup_mock = AsyncMock(name="cleanup_resources")
    monkeypatch.setattr(app_main, "_cleanup_service_resources", cleanup_mock)

    def _fail_bot(*_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("Bot should not be created in DEV_DRY_RUN mode")

    def _fail_dispatcher(*_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("Dispatcher should not be created in DEV_DRY_RUN mode")

    monkeypatch.setattr(app_main, "Bot", _fail_bot)
    monkeypatch.setattr(app_main, "Dispatcher", _fail_dispatcher)

    def _fail_scheduler(*_args, **_kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("Scheduler must not start in DEV_DRY_RUN mode")

    monkeypatch.setattr(app_main, "start_scheduler", _fail_scheduler)

    start_background_mock = AsyncMock(
        side_effect=AssertionError("background queue should be skipped")
    )
    monkeypatch.setattr(app_main, "start_background_queue", start_background_mock)

    await app_main.main()

    init_db_mock.assert_awaited_once()
    setup_service_mock.assert_awaited_once()
    wait_mock.assert_awaited_once()
    cleanup_mock.assert_awaited_once_with(runner, site)
    start_background_mock.assert_not_called()
