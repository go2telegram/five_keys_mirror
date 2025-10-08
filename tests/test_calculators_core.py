from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import calc_unified


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


def _patch_infrastructure(monkeypatch) -> AsyncMock:
    monkeypatch.setattr(calc_unified, "session_scope", _dummy_scope)
    monkeypatch.setattr(calc_unified.users_repo, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(calc_unified, "set_last_plan", AsyncMock())
    monkeypatch.setattr(calc_unified.events_repo, "log", AsyncMock())
    log_error = AsyncMock()
    monkeypatch.setattr(calc_unified.calculator_results_repo, "log_error", log_error)
    log_success = AsyncMock()
    monkeypatch.setattr(calc_unified.calculator_results_repo, "log_success", log_success)
    send_mock = AsyncMock()
    monkeypatch.setattr(calc_unified, "send_product_cards", send_mock)
    return SimpleNamespace(send=send_mock, log_success=log_success, log_error=log_error)


@pytest.mark.asyncio
async def test_water_calculator_smoke(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 501
    calc_unified.SESSIONS.pop(user_id, None)
    start_cb = _make_callback(user_id, "calc:water")
    await calc_unified._start_flow(start_cb, "water")

    session = calc_unified.SESSIONS[user_id]
    assert session["step_index"] == 0

    weight_msg = _make_message(user_id, "68")
    await calc_unified._dispatch_message(weight_msg)
    assert calc_unified.SESSIONS[user_id]["step_index"] == 1

    activity_cb = _make_callback(user_id, "calc:flow:water:opt:activity:moderate")
    await calc_unified._dispatch_callback(activity_cb)
    assert calc_unified.SESSIONS[user_id]["step_index"] == 2

    climate_cb = _make_callback(user_id, "calc:flow:water:opt:climate:hot")
    await calc_unified._dispatch_callback(climate_cb)

    calc_unified.set_last_plan.assert_awaited_once()
    calc_unified.events_repo.log.assert_awaited_once()
    patches.log_success.assert_awaited_once()
    patches.log_error.assert_not_called()
    patches.send.assert_awaited_once()
    _, kwargs = patches.send.await_args
    assert kwargs.get("reply_markup") is not None
    assert calc_unified.SESSIONS.get(user_id) is None


@pytest.mark.asyncio
async def test_kcal_calculator_smoke(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 602
    calc_unified.SESSIONS.pop(user_id, None)
    start_cb = _make_callback(user_id, "calc:kcal")
    await calc_unified._start_flow(start_cb, "kcal")

    session = calc_unified.SESSIONS[user_id]
    assert session["step_index"] == 0

    sex_cb = _make_callback(user_id, "calc:flow:kcal:opt:sex:m")
    await calc_unified._dispatch_callback(sex_cb)
    assert calc_unified.SESSIONS[user_id]["step_index"] == 1

    await calc_unified._dispatch_message(_make_message(user_id, "32"))
    await calc_unified._dispatch_message(_make_message(user_id, "80"))
    await calc_unified._dispatch_message(_make_message(user_id, "182"))
    assert calc_unified.SESSIONS[user_id]["step_index"] == 4

    activity_cb = _make_callback(user_id, "calc:flow:kcal:opt:activity:155")
    await calc_unified._dispatch_callback(activity_cb)
    assert calc_unified.SESSIONS[user_id]["step_index"] == 5

    goal_cb = _make_callback(user_id, "calc:flow:kcal:opt:goal:maintain")
    await calc_unified._dispatch_callback(goal_cb)

    calc_unified.set_last_plan.assert_awaited_once()
    calc_unified.events_repo.log.assert_awaited_once()
    patches.log_success.assert_awaited_once()
    patches.log_error.assert_not_called()
    patches.send.assert_awaited_once()
    assert calc_unified.SESSIONS.get(user_id) is None


@pytest.mark.asyncio
async def test_macros_calculator_smoke(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 703
    calc_unified.SESSIONS.pop(user_id, None)
    start_cb = _make_callback(user_id, "calc:macros")
    await calc_unified._start_flow(start_cb, "macros")

    session = calc_unified.SESSIONS[user_id]
    assert session["step_index"] == 0

    await calc_unified._dispatch_message(_make_message(user_id, "72"))
    assert calc_unified.SESSIONS[user_id]["step_index"] == 1

    goal_cb = _make_callback(user_id, "calc:flow:macros:opt:goal:loss")
    await calc_unified._dispatch_callback(goal_cb)
    assert calc_unified.SESSIONS[user_id]["step_index"] == 2

    pref_cb = _make_callback(user_id, "calc:flow:macros:opt:preference:balanced")
    await calc_unified._dispatch_callback(pref_cb)

    calc_unified.set_last_plan.assert_awaited_once()
    calc_unified.events_repo.log.assert_awaited_once()
    patches.log_success.assert_awaited_once()
    patches.log_error.assert_not_called()
    patches.send.assert_awaited_once()
    assert calc_unified.SESSIONS.get(user_id) is None


@pytest.mark.asyncio
async def test_bmi_calculator_smoke(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 804
    calc_unified.SESSIONS.pop(user_id, None)
    start_cb = _make_callback(user_id, "calc:bmi")
    await calc_unified._start_flow(start_cb, "bmi")

    session = calc_unified.SESSIONS[user_id]
    assert session["step_index"] == 0

    await calc_unified._dispatch_message(_make_message(user_id, "180"))
    assert calc_unified.SESSIONS[user_id]["step_index"] == 1

    await calc_unified._dispatch_message(_make_message(user_id, "80"))

    calc_unified.set_last_plan.assert_awaited_once()
    calc_unified.events_repo.log.assert_awaited_once()
    patches.log_success.assert_awaited_once()
    patches.log_error.assert_not_called()
    patches.send.assert_awaited_once()
    assert calc_unified.SESSIONS.get(user_id) is None


@pytest.mark.asyncio
async def test_water_calculator_tags(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 905
    calc_unified.SESSIONS.pop(user_id, None)
    await calc_unified._start_flow(_make_callback(user_id, "calc:water"), "water")

    await calc_unified._dispatch_message(_make_message(user_id, "50"))
    await calc_unified._dispatch_callback(_make_callback(user_id, "calc:flow:water:opt:activity:low"))
    await calc_unified._dispatch_callback(_make_callback(user_id, "calc:flow:water:opt:climate:temperate"))

    args = patches.log_success.await_args.kwargs
    assert "electrolytes" in args.get("tags", [])


@pytest.mark.asyncio
async def test_macros_calculator_tags(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 906
    calc_unified.SESSIONS.pop(user_id, None)
    await calc_unified._start_flow(_make_callback(user_id, "calc:macros"), "macros")

    await calc_unified._dispatch_message(_make_message(user_id, "60"))
    await calc_unified._dispatch_callback(_make_callback(user_id, "calc:flow:macros:opt:goal:maintain"))
    await calc_unified._dispatch_callback(_make_callback(user_id, "calc:flow:macros:opt:preference:lowcarb"))

    args = patches.log_success.await_args.kwargs
    assert set(args.get("tags", [])) >= {"protein_low", "collagen"}


@pytest.mark.asyncio
async def test_bmi_calculator_tags(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 907
    calc_unified.SESSIONS.pop(user_id, None)
    await calc_unified._start_flow(_make_callback(user_id, "calc:bmi"), "bmi")

    await calc_unified._dispatch_message(_make_message(user_id, "160"))
    await calc_unified._dispatch_message(_make_message(user_id, "90"))

    args = patches.log_success.await_args.kwargs
    assert "weight_management" in args.get("tags", [])


@pytest.mark.asyncio
async def test_invalid_input_logs_error(monkeypatch):
    patches = _patch_infrastructure(monkeypatch)

    user_id = 908
    calc_unified.SESSIONS.pop(user_id, None)
    await calc_unified._start_flow(_make_callback(user_id, "calc:water"), "water")

    await calc_unified._dispatch_message(_make_message(user_id, "abc"))

    patches.log_error.assert_awaited_once()
    kwargs = patches.log_error.await_args.kwargs
    assert kwargs["step"] == "weight"
    assert kwargs["raw_value"] == "abc"
    patches.log_success.assert_not_called()
