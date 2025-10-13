from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.feature_flags import FeatureFlagManager


@pytest.mark.anyio
async def test_stage_defaults_enabled(tmp_path) -> None:
    settings = Settings(
        ENVIRONMENT="stage",
        FEATURE_FLAGS_FILE=str(tmp_path / "flags.json"),
    )
    manager = FeatureFlagManager(settings, use_redis=False)
    await manager.initialize()

    snapshot = manager.snapshot()
    assert snapshot
    assert all(snapshot[flag] is True for flag in manager.available())


@pytest.mark.anyio
async def test_toggle_persists_to_file(tmp_path) -> None:
    storage_path = tmp_path / "flags.json"
    settings = Settings(
        ENVIRONMENT="prod",
        CANARY_PERCENT=0,
        FEATURE_FLAGS_FILE=str(storage_path),
    )
    manager = FeatureFlagManager(settings, use_redis=False)
    await manager.initialize()

    await manager.set_flag("FF_NEW_ONBOARDING", True)
    assert json.loads(storage_path.read_text(encoding="utf-8")) == {"FF_NEW_ONBOARDING": True}

    # Reload to ensure overrides are picked up
    reloaded = FeatureFlagManager(settings, use_redis=False)
    await reloaded.initialize()
    assert reloaded.snapshot()["FF_NEW_ONBOARDING"] is True


@pytest.mark.anyio
async def test_canary_rollout_distribution(tmp_path) -> None:
    settings = Settings(
        ENVIRONMENT="prod",
        CANARY_PERCENT=30,
        FEATURE_FLAGS_FILE=str(tmp_path / "flags.json"),
    )
    manager = FeatureFlagManager(settings, use_redis=False)
    await manager.initialize()

    total = 1000
    enabled = sum(
        1
        for user_id in range(1, total + 1)
        if manager.is_enabled("FF_NEW_ONBOARDING", user_id=user_id)
    )
    share = enabled / total

    assert 0.25 <= share <= 0.35
