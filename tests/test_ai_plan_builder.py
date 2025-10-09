from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("aiosqlite")

from app.reco import ai_plan


@asynccontextmanager
async def _dummy_scope():
    yield SimpleNamespace()


@pytest.mark.asyncio
async def test_ai_plan_enforces_structure(monkeypatch):
    monkeypatch.setattr(ai_plan, "session_scope", _dummy_scope)
    monkeypatch.setattr(ai_plan, "ai_generate", AsyncMock(return_value="Сделай зарядку"))

    fake_event = SimpleNamespace(
        ts=datetime.now(timezone.utc),
        meta={"quiz": "energy", "level": "mid"},
        name="quiz_finish",
    )

    async def _fake_latest(session, user_id, name, limit):
        return [fake_event]

    monkeypatch.setattr(ai_plan, "_latest_events", _fake_latest)
    monkeypatch.setattr(
        ai_plan.events_repo,
        "recent_plans",
        AsyncMock(return_value=[SimpleNamespace(ts=datetime.now(timezone.utc), meta={"title": "План"})]),
    )
    monkeypatch.setattr(ai_plan.user_profiles_repo, "update_plan", AsyncMock())
    monkeypatch.setattr(ai_plan, "commit_safely", AsyncMock())

    plan_text = await ai_plan.build_ai_plan(77, horizon="7d")
    assert "🗓 План на 7d" in plan_text
    assert "### Утро" in plan_text
    assert "### День" in plan_text
    assert "### Вечер" in plan_text
