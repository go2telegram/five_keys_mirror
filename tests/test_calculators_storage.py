from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.handlers import calc_kcal, calc_water
from app.repo import calculators as calculators_repo

pytest.importorskip("aiosqlite")


def _make_message(user_id: int, text: str) -> MagicMock:
    message = MagicMock()
    message.from_user = SimpleNamespace(id=user_id, username="tester")
    message.text = text
    message.answer = AsyncMock()
    return message


def _make_callback(user_id: int, data: str) -> MagicMock:
    message = MagicMock()
    message.edit_text = AsyncMock()
    message.answer = AsyncMock()
    callback = MagicMock()
    callback.data = data
    callback.from_user = SimpleNamespace(id=user_id, username="tester")
    callback.message = message
    callback.answer = AsyncMock()
    return callback


@asynccontextmanager
async def _session_scope(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_water_result_persisted(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        monkeypatch.setattr(calc_water, "session_scope", lambda: _session_scope(session_factory))
        monkeypatch.setattr(calc_water, "send_product_cards", AsyncMock())
        monkeypatch.setattr(calc_water, "pick_for_context", lambda *_, **__: [])

        user_id = 111
        await calc_water.start_water_calc(_make_callback(user_id, "calc:water"))
        await calc_water.handle_message(_make_message(user_id, "68"))
        await calc_water.choose_activity(_make_callback(user_id, "calc:water:activity:moderate"))
        await calc_water.choose_climate(_make_callback(user_id, "calc:water:climate:hot"))

        async with session_factory() as session:
            results = await calculators_repo.get_by_user(session, user_id)
    finally:
        await engine.dispose()

    assert len(results) == 1
    result = results[0]
    assert result.kind == "water"
    assert result.payload["liters"] == 3.1
    assert result.payload["glasses"] == 12
    assert result.payload["activity"] == "moderate"
    assert result.payload["climate"] == "hot"
    assert result.payload["weight"] == 68.0
    assert result.created_at is not None


@pytest.mark.asyncio
async def test_kcal_result_persisted(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        monkeypatch.setattr(calc_kcal, "session_scope", lambda: _session_scope(session_factory))
        monkeypatch.setattr(calc_kcal, "send_product_cards", AsyncMock())
        monkeypatch.setattr(calc_kcal, "pick_for_context", lambda *_, **__: [])

        user_id = 222
        await calc_kcal.start_kcal(_make_callback(user_id, "calc:kcal"))
        await calc_kcal.choose_sex(_make_callback(user_id, "calc:kcal:sex:m"))
        await calc_kcal.handle_message(_make_message(user_id, "32"))
        await calc_kcal.handle_message(_make_message(user_id, "80"))
        await calc_kcal.handle_message(_make_message(user_id, "182"))
        await calc_kcal.choose_activity(_make_callback(user_id, "calc:kcal:activity:155"))
        await calc_kcal.choose_goal(_make_callback(user_id, "calc:kcal:goal:maintain"))

        async with session_factory() as session:
            results = await calculators_repo.get_by_user(session, user_id)
    finally:
        await engine.dispose()

    assert len(results) == 1
    result = results[0]
    assert result.kind == "kcal"
    assert result.payload["base"] == 1782
    assert result.payload["tdee"] == 2763
    assert result.payload["target"] == 2763
    assert result.payload["goal"] == "maintain"
    assert result.payload["factor"] == 1.55
    assert result.payload["age"] == 32
    assert result.payload["weight"] == 80.0
    assert result.payload["height"] == 182
    assert result.payload["sex"] == "m"
    assert result.created_at is not None
