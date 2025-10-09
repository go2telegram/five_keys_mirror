import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from app import main as app_main


@pytest.mark.anyio("asyncio")
async def test_doctor_endpoint_repairs(monkeypatch):
    async def fake_current_revision(db_url=None):  # noqa: ANN001
        return "rev-current"

    async def fake_head_revision(db_url=None):  # noqa: ANN001
        return "rev-head"

    state = {"first": True}

    async def fake_list_tables(db_url=None):  # noqa: ANN001
        if state["first"]:
            return ["_alembic_tmp_demo"]
        return []

    async def fake_repair(db_url=None):  # noqa: ANN001
        state["first"] = False
        return ["_alembic_tmp_demo"]

    monkeypatch.setattr(app_main, "current_revision", fake_current_revision)
    monkeypatch.setattr(app_main, "head_revision", fake_head_revision)
    monkeypatch.setattr(app_main, "list_stale_alembic_tables", fake_list_tables)
    monkeypatch.setattr(app_main, "repair_stale_alembic_tables", fake_repair)

    request = make_mocked_request("GET", "/doctor?repair=1", app=web.Application())
    response = await app_main._handle_doctor(request)
    payload = json.loads(response.text)

    assert payload["status"] == "ok"
    assert payload["repair_performed"] is True
    assert payload["repaired"] == ["_alembic_tmp_demo"]
    assert payload["tmp_tables"] == []
    assert payload["current_revision"] == "rev-current"
    assert payload["head_revision"] == "rev-head"


@pytest.mark.anyio("asyncio")
async def test_doctor_endpoint_without_repair(monkeypatch):
    async def fake_current_revision(db_url=None):  # noqa: ANN001
        return "rev-current"

    async def fake_head_revision(db_url=None):  # noqa: ANN001
        return "rev-head"

    async def fake_list_tables(db_url=None):  # noqa: ANN001
        return []

    async def fake_repair(db_url=None):  # noqa: ANN001
        raise AssertionError("repair should not be called")

    monkeypatch.setattr(app_main, "current_revision", fake_current_revision)
    monkeypatch.setattr(app_main, "head_revision", fake_head_revision)
    monkeypatch.setattr(app_main, "list_stale_alembic_tables", fake_list_tables)
    monkeypatch.setattr(app_main, "repair_stale_alembic_tables", fake_repair)

    request = make_mocked_request("GET", "/doctor", app=web.Application())
    response = await app_main._handle_doctor(request)
    payload = json.loads(response.text)

    assert payload["repair_performed"] is False
    assert payload["repaired"] == []
    assert payload["tmp_tables"] == []
