import datetime as dt
from types import SimpleNamespace

import pytest

import app.services.analytics_reports as reports


def test_funnel_stats_rates():
    stats = reports.FunnelStats(shows=100, clicks=25, buy_started=10, buy_success=4)
    assert pytest.approx(stats.ctr(), rel=1e-6) == 0.25
    assert pytest.approx(stats.checkout_rate(), rel=1e-6) == 0.4


def test_aggregate_ctr_groups_sources():
    events = [
        SimpleNamespace(name="premium_cta_click", meta={"source": "calc:energy"}),
        SimpleNamespace(name="premium_cta_click", meta={"source": "calc:energy"}),
        SimpleNamespace(name="premium_cta_click", meta={"source": "menu"}),
        SimpleNamespace(name="premium_info_open", meta={"source": "cta:calc:energy"}),
        SimpleNamespace(name="premium_info_open", meta={"source": "cta:menu"}),
        SimpleNamespace(name="premium_info_open", meta={"source": "cta:menu"}),
    ]
    rows = reports.aggregate_ctr(events)
    data = {row.source: row for row in rows}
    assert data["calc:energy"].clicks == 2
    assert data["calc:energy"].shows == 1
    assert data["menu"].clicks == 1
    assert data["menu"].shows == 2


def test_aggregate_cohorts_groups_weeks():
    monday = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    tuesday = monday + dt.timedelta(days=1)
    users = [
        SimpleNamespace(id=1, created=monday),
        SimpleNamespace(id=2, created=tuesday),
        SimpleNamespace(id=3, created=monday + dt.timedelta(days=8)),
    ]
    subscriptions = [
        SimpleNamespace(user_id=1, started_at=monday + dt.timedelta(days=2)),
        SimpleNamespace(user_id=3, started_at=monday + dt.timedelta(days=9)),
    ]
    rows = reports.aggregate_cohorts(users, subscriptions, weeks=4)
    data = {row.week_start: row for row in rows}
    assert data[monday.date()].new_users == 2
    assert data[monday.date()].conversions == 1
    later_week = (monday + dt.timedelta(days=7)).date()
    assert data[later_week].new_users == 1
    assert data[later_week].conversions == 1


def test_export_csv_handles_permission(monkeypatch):
    monkeypatch.setattr(reports, "_ensure_export_dir", lambda _path: False)
    path = reports.export_csv("test.csv", ["a"], [[1]])
    assert path is None


def test_export_csv_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "EXPORT_DIR", tmp_path)
    path = reports.export_csv("sample.csv", ["col"], [["value"]])
    assert path is not None
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() == "col\nvalue"
