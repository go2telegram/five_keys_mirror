import json
from unittest.mock import AsyncMock

import pytest

from app import dashboard


@pytest.mark.asyncio
async def test_gather_doctor_context(monkeypatch):
    monkeypatch.setattr(dashboard, "current_revision", AsyncMock(return_value="rev1"))
    monkeypatch.setattr(dashboard, "head_revision", AsyncMock(return_value="rev2"))
    monkeypatch.setattr(dashboard, "_catalog_state", lambda: (42, "2024-05-01", "v5", []))

    context = await dashboard._gather_doctor_context()
    assert context["database"]["current_revision"] == "rev1"
    assert context["database"]["head_revision"] == "rev2"
    assert context["catalog"]["total"] == 42
    assert context["catalog"]["version"] == "v5"


@pytest.mark.asyncio
async def test_analytics_summary_response(monkeypatch):
    sample = {
        "leads_total": 10,
        "leads_recent": 3,
        "quiz_total": 20,
        "calc_total": 5,
        "plans_total": 8,
        "ctr": 40.0,
        "quiz_chart": "",
        "calc_chart": "",
        "ctr_chart": "",
        "top_products": [],
        "catalog_goals": [],
        "recent_leads": [],
        "catalog_total": 0,
        "catalog_updated": "—",
        "catalog_version": "v1",
    }
    monkeypatch.setattr(dashboard, "_gather_dashboard_context", AsyncMock(return_value=sample))

    response = await dashboard.analytics(None)
    payload = json.loads(response.body)
    assert payload["quiz_total"] == 20
    assert payload["calc_total"] == 5
    assert payload["plans_total"] == 8
    assert "ctr" in payload
