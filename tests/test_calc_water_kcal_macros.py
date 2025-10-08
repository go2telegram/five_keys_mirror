from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import calc, calc_kcal, calc_macros, calc_water
import app.handlers.calc_common as calc_common


@asynccontextmanager
async def _dummy_scope():
    yield object()


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


@pytest.mark.asyncio
async def test_water_calculator_flow(monkeypatch):
    monkeypatch.setattr(calc_water, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc_water.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc_water, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc_water.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(calc_water, "send_calc_summary", send_mock)

    user_id = 501
    start_cb = _make_callback(user_id, "calc:water")
    await calc_water.start_water_calc(start_cb)

    assert calc_water.SESSIONS[user_id]["step"] == "weight"

    weight_message = _make_message(user_id, "68")
    await calc_water.handle_message(weight_message)
    assert calc_water.SESSIONS[user_id]["step"] == "activity"

    activity_cb = _make_callback(user_id, "calc:water:activity:moderate")
    await calc_water.choose_activity(activity_cb)
    assert calc_water.SESSIONS[user_id]["step"] == "climate"

    climate_cb = _make_callback(user_id, "calc:water:climate:hot")
    await calc_water.choose_climate(climate_cb)

    calc_water.set_last_plan.assert_awaited()
    calc_water.events_repo.log.assert_awaited()
    send_mock.assert_awaited()
    assert user_id not in calc_water.SESSIONS


@pytest.mark.asyncio
async def test_kcal_calculator_flow(monkeypatch):
    monkeypatch.setattr(calc_kcal, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc_kcal.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc_kcal, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc_kcal.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(calc_kcal, "send_calc_summary", send_mock)

    user_id = 602
    await calc_kcal.start_kcal(_make_callback(user_id, "calc:kcal"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "sex"

    await calc_kcal.choose_sex(_make_callback(user_id, "calc:kcal:sex:m"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "age"

    await calc_kcal.handle_message(_make_message(user_id, "32"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "weight"

    await calc_kcal.handle_message(_make_message(user_id, "80"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "height"

    await calc_kcal.handle_message(_make_message(user_id, "182"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "activity"

    await calc_kcal.choose_activity(_make_callback(user_id, "calc:kcal:activity:155"))
    assert calc_kcal.SESSIONS[user_id]["step"] == "goal"

    await calc_kcal.choose_goal(_make_callback(user_id, "calc:kcal:goal:maintain"))

    calc_kcal.set_last_plan.assert_awaited()
    calc_kcal.events_repo.log.assert_awaited()
    send_mock.assert_awaited()
    assert user_id not in calc_kcal.SESSIONS


@pytest.mark.asyncio
async def test_macros_calculator_flow(monkeypatch):
    monkeypatch.setattr(calc_macros, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc_macros.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc_macros, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc_macros.events_repo, "log", AsyncMock())
    send_mock = AsyncMock()
    monkeypatch.setattr(calc_macros, "send_calc_summary", send_mock)

    user_id = 703
    await calc_macros.start_macros(_make_callback(user_id, "calc:macros"))
    assert calc_macros.SESSIONS[user_id]["step"] == "weight"

    await calc_macros.handle_message(_make_message(user_id, "72"))
    assert calc_macros.SESSIONS[user_id]["step"] == "goal"

    await calc_macros.choose_goal(_make_callback(user_id, "calc:macros:goal:loss"))
    assert calc_macros.SESSIONS[user_id]["step"] == "preference"

    await calc_macros.choose_preference(_make_callback(user_id, "calc:macros:pref:balanced"))

    calc_macros.set_last_plan.assert_awaited()
    calc_macros.events_repo.log.assert_awaited()
    send_mock.assert_awaited()


@pytest.mark.asyncio
async def test_calc_recommendations_button(monkeypatch):
    user_id = 904
    result = calc_common.CalcResult(
        calc="water",
        title="test",
        products=["OMEGA3"],
        headline="headline",
        bullets=["bullet"],
        back_cb="calc:menu",
    )
    calc_common._RESULTS.put(user_id, result)

    send_mock = AsyncMock()
    monkeypatch.setattr(calc, "send_product_cards", send_mock)

    callback = _make_callback(user_id, "calc:recommend:water")
    await calc.calc_recommendations(callback)

    send_mock.assert_awaited_with(
        callback,
        result.title,
        result.products,
        headline=result.headline,
        bullets=result.bullets,
        back_cb=result.back_cb,
    )
    calc_common._RESULTS.clear(user_id)
    assert user_id not in calc_macros.SESSIONS
