"""FastAPI-powered admin dashboard for analytics."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import plotly.graph_objects as go
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from plotly.io import to_html
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.loader import load_catalog
from app.config import settings
from app.db.models import Event, Lead
from app.db.session import session_scope
from app.growth import attribution as growth_attribution
from app.link_manager import (
    active_set_name,
    audit_actor,
    delete_product_link,
    export_set,
    get_all_product_links,
    get_register_link,
    list_sets,
    set_bulk_links,
    set_product_link,
    set_register_link,
    switch_set,
)
from app.repo import events as events_repo, leads as leads_repo
from app.utils.build import get_build_info

app = FastAPI(title="Five Keys Admin Dashboard")


def _require_token(request: Request) -> None:
    token = settings.DASHBOARD_TOKEN
    if not token:
        raise HTTPException(status_code=503, detail="Dashboard token is not configured")

    provided: str | None = None
    header = request.headers.get("Authorization")
    if header:
        scheme, _, value = header.partition(" ")
        provided = value.strip() if scheme.lower() == "bearer" else header.strip()
    if provided is None:
        provided = request.query_params.get("token")

    if provided != token:
        raise HTTPException(status_code=401, detail="Unauthorized")


class RegisterUpdate(BaseModel):
    url: str = Field(..., min_length=1, description="https URL for registration")


class ProductUpdate(BaseModel):
    product_id: str = Field(..., min_length=1, description="Product identifier")
    url: str = Field(..., min_length=1, description="https URL override")


class ProductDelete(BaseModel):
    product_id: str = Field(..., min_length=1, description="Product identifier")


class ImportRequest(BaseModel):
    register: str | None = None
    products: Dict[str, str] | None = None


class SwitchRequest(BaseModel):
    target: str = Field(..., min_length=1, description="Target link set name")


async def _collect_event_stats(
    session: AsyncSession,
    name: str,
    key: str,
    limit: int | None = None,
) -> Tuple[Counter[str], int]:
    stmt = select(Event.meta, Event.ts).where(Event.name == name).order_by(Event.ts.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    counts: Counter[str] = Counter()
    for meta, _ in rows:
        payload = meta or {}
        label = str(payload.get(key) or "unknown")
        counts[label] += 1
    return counts, sum(counts.values())


async def _collect_plan_stats(session: AsyncSession, limit: int | None = None) -> Tuple[int, Counter[str]]:
    stmt = select(Event.meta).where(Event.name == "plan_generated").order_by(Event.ts.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    total = 0
    products: Counter[str] = Counter()
    for meta in rows:
        total += 1
        payload = meta or {}
        for code in payload.get("products", []) or []:
            if code:
                products[str(code)] += 1
    return total, products


async def _collect_lead_details(
    session: AsyncSession,
    limit: int = 15,
) -> Tuple[int, int, List[Dict[str, Any]]]:
    total = await leads_repo.count(session)
    now = datetime.now(timezone.utc)
    recent_count_stmt = select(func.count()).where(Lead.ts >= now - timedelta(days=7))
    recent_count = (await session.execute(recent_count_stmt)).scalar_one()
    stmt = select(Lead).order_by(Lead.ts.desc()).limit(limit)
    leads = list((await session.execute(stmt)).scalars())
    user_ids = {lead.user_id for lead in leads if lead.user_id is not None}
    quiz_map = await events_repo.latest_by_users(session, "quiz_finish", user_ids)
    plan_map = await events_repo.latest_by_users(session, "plan_generated", user_ids)

    rows: List[Dict[str, Any]] = []
    for lead in leads:
        quiz_event = quiz_map.get(lead.user_id) if lead.user_id is not None else None
        plan_event = plan_map.get(lead.user_id) if lead.user_id is not None else None
        quiz_meta = quiz_event.meta if quiz_event is not None else {}
        plan_meta = plan_event.meta if plan_event is not None else {}
        rows.append(
            {
                "name": lead.name,
                "phone": lead.phone,
                "created_at": lead.ts,
                "quiz": quiz_meta.get("quiz"),
                "quiz_level": quiz_meta.get("level"),
                "plan": plan_meta.get("title"),
                "products": ", ".join(str(code) for code in plan_meta.get("products", []) or []),
            }
        )
    return total, recent_count, rows


def _build_bar_chart(title: str, counter: Counter[str], color: str = "#2563eb") -> str:
    if not counter:
        return "<div class='chart-empty'>Недостаточно данных</div>"
    items = counter.most_common()
    labels = [item[0] for item in items]
    values = [item[1] for item in items]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=color))
    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=40, r=40, t=60, b=40),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
    )
    return to_html(fig, include_plotlyjs=False, full_html=False)


def _build_ctr_gauge(value: float) -> str:
    max_range = max(100.0, value * 1.3 if value else 100.0)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=round(value, 2),
            number={"suffix": "%"},
            title={"text": "Quiz → Recommendation CTR"},
            gauge={
                "axis": {"range": [0, max_range]},
                "bar": {"color": "#10b981"},
                "bgcolor": "#0f172a",
                "bordercolor": "#1e293b",
                "steps": [
                    {"range": [0, max_range * 0.25], "color": "#1f2937"},
                    {"range": [max_range * 0.25, max_range * 0.6], "color": "#0f172a"},
                    {"range": [max_range * 0.6, max_range], "color": "#0b2539"},
                ],
            },
        )
    )
    fig.update_layout(
        height=320,
        margin=dict(l=40, r=40, t=60, b=40),
        paper_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
    )
    return to_html(fig, include_plotlyjs=False, full_html=False)


def _build_utm_chart(items: List[Tuple[growth_attribution.UtmKey, growth_attribution.UtmFunnelMetrics]]) -> str:
    if not items:
        return "<div class='chart-empty'>Нет данных по UTM-источникам</div>"

    labels = [growth_attribution.format_utm_label(key) for key, _ in items]
    registrations = [metrics.registrations for _, metrics in items]
    quizzes = [metrics.quiz_starts for _, metrics in items]
    recommendations = [metrics.recommendations for _, metrics in items]
    premiums = [metrics.premium_buys for _, metrics in items]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Регистрации", x=labels, y=registrations, marker_color="#22d3ee"))
    fig.add_trace(go.Bar(name="Квизы", x=labels, y=quizzes, marker_color="#2563eb"))
    fig.add_trace(go.Bar(name="Рекомендации", x=labels, y=recommendations, marker_color="#10b981"))
    fig.add_trace(go.Bar(name="Подписки", x=labels, y=premiums, marker_color="#f97316"))

    fig.update_layout(
        barmode="group",
        title="UTM-воронка",
        height=420,
        margin=dict(l=40, r=40, t=60, b=100),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
        xaxis=dict(tickangle=-30, automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
    )
    return to_html(fig, include_plotlyjs=False, full_html=False)


def _format_dt(dt: datetime | None) -> str:
    if not isinstance(dt, datetime):
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _render_table(rows: List[Tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td>{idx + 1}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>" for idx, cells in enumerate(rows)
    )
    return body or "<tr><td colspan='3' class='muted'>Нет данных</td></tr>"


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str):
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_load_history() -> List[Dict[str, Any]]:
    report_path = Path(__file__).resolve().parent.parent / "build" / "reports" / "load.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        return payload["runs"]
    return []


def _build_load_chart(history: List[Dict[str, Any]]) -> str:
    points: List[tuple[datetime, float]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        timestamp = _parse_iso_timestamp(entry.get("timestamp"))
        latency_container = entry.get("latency")
        latency = None
        if isinstance(latency_container, dict):
            latency = latency_container.get("p95")
        if timestamp is None or not isinstance(latency, (int, float)):
            continue
        points.append((timestamp, float(latency)))

    if not points:
        return "<div class='chart-empty'>Нет данных нагрузочного теста</div>"

    points.sort(key=lambda item: item[0])
    x_values = [point[0].strftime("%Y-%m-%d %H:%M") for point in points]
    y_values = [point[1] for point in points]

    fig = go.Figure(
        go.Scatter(
            x=x_values,
            y=y_values,
            mode="lines+markers",
            line=dict(color="#f97316", width=2),
            marker=dict(size=6),
        )
    )
    fig.update_layout(
        title="P95 отклик сервисов",
        height=360,
        margin=dict(l=40, r=40, t=60, b=40),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
        yaxis=dict(title="мс"),
        xaxis=dict(title="Запуск", tickangle=-35),
    )
    return to_html(fig, include_plotlyjs=False, full_html=False)


def _render_dashboard_html(context: Dict[str, Any]) -> str:
    quiz_chart = context["quiz_chart"]
    calc_chart = context["calc_chart"]
    ctr_chart = context["ctr_chart"]
    load_chart = context["load_chart"]
    utm_chart = context["utm_chart"]
    top_products_rows = _render_table(context["top_products"])
    goal_rows = _render_table(context["catalog_goals"])
    _commit = (
        f"{context['build_commit_short']} : "
        f"{context['build_info']['timestamp']}"
    )
    lead_rows_html = (
        "".join(
            "<tr>"
            f"<td>{_format_dt(row['created_at'])}</td>"
            f"<td>{row['name']}</td>"
            f"<td>{row['phone']}</td>"
            f"<td>{row['quiz'] or '—'}</td>"
            f"<td>{row['plan'] or '—'}</td>"
            f"<td>{row['products'] or '—'}</td>"
            "</tr>"
            for row in context["recent_leads"]
        )
        or "<tr><td colspan='6' class='muted'>Нет заявок</td></tr>"
    )

    plotly_script = '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'

    return f"""
<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <title>Five Keys Admin Dashboard</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap\" rel=\"stylesheet\" />
  <style>
    body {{
      font-family: 'Inter', Arial, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      margin: 0;
      padding: 0;
    }}
    header {{
      padding: 24px 32px;
      background: #111827;
      border-bottom: 1px solid #1f2937;
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 600;
    }}
    main {{
      padding: 24px 32px 48px;
      display: grid;
      gap: 32px;
    }}
    .cards {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }}
    .card {{
      background: #111827;
      padding: 20px;
      border-radius: 16px;
      border: 1px solid #1f2937;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.35);
    }}
    .card h2 {{
      margin: 0 0 12px 0;
      font-size: 18px;
      color: #93c5fd;
    }}
    .metric {{
      font-size: 32px;
      font-weight: 600;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      font-size: 14px;
    }}
    th, td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid #1f2937;
    }}
    th {{
      color: #93c5fd;
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: 0.08em;
    }}
    tr:hover td {{
      background: rgba(37, 99, 235, 0.08);
    }}
    .muted {{
      color: #64748b;
      text-align: center;
    }}
    .build-info {{
      margin-top: 8px;
      color: #94a3b8;
      font-size: 14px;
    }}
    .charts {{
      display: grid;
      gap: 24px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }}
    .chart-empty {{
      padding: 40px;
      text-align: center;
      color: #64748b;
      border: 1px dashed #1f2937;
      border-radius: 16px;
    }}
  </style>
  {plotly_script}
</head>
<body>
  <header>
    <h1>Аналитика Five Keys</h1>
    <p class="build-info">Версия {context["build_info"]["version"]} · commit {_commit}</p>
  </header>
  <main>
    <section class=\"cards\">
      <article class=\"card\">
        <h2>Лиды всего</h2>
        <div class=\"metric\">{context["leads_total"]}</div>
        <p class=\"muted\">За 7 дней: {context["leads_recent"]}</p>
      </article>
      <article class=\"card\">
        <h2>Завершено квизов</h2>
        <div class=\"metric\">{context["quiz_total"]}</div>
      </article>
      <article class=\"card\">
        <h2>Калькуляторы</h2>
        <div class=\"metric\">{context["calc_total"]}</div>
      </article>
      <article class=\"card\">
        <h2>Планы рекомендаций</h2>
        <div class=\"metric\">{context["plans_total"]}</div>
      </article>
      <article class=\"card\">
        <h2>CTR (квиз → план)</h2>
        <div class=\"metric\">{context["ctr"]:.2f}%</div>
      </article>
      <article class=\"card\">
        <h2>Каталог</h2>
        <div class=\"metric\">{context["catalog_total"]} SKU</div>
        <p class=\"muted\">Обновлено: {context["catalog_updated"]}</p>
      </article>
      <article class=\"card\">
        <h2>Нагрузочный тест P95</h2>
        <div class=\"metric\">{context["load_p95"]}</div>
        <p class=\"muted\">Ошибки: {context["load_errors"]} · {context["load_timestamp"]}</p>
      </article>
      <article class=\"card\">
        <h2>UTM регистрации</h2>
        <div class=\"metric\">{context["utm_total_reg"]}</div>
        <p class=\"muted\">CTR: {context["utm_ctr"]:.1f}% · CR: {context["utm_cr"]:.1f}%</p>
      </article>
    </section>

    <section class=\"charts\">
      <div class=\"card\">{utm_chart}</div>
      <div class=\"card\">{quiz_chart}</div>
      <div class=\"card\">{calc_chart}</div>
      <div class=\"card\">{ctr_chart}</div>
      <div class=\"card\">{load_chart}</div>
    </section>

    <section class=\"cards\">
      <article class=\"card\">
        <h2>Топ рекомендаций</h2>
        <table>
          <thead>
            <tr><th>#</th><th>Продукт</th><th>Количество</th></tr>
          </thead>
          <tbody>
            {top_products_rows}
          </tbody>
        </table>
      </article>
      <article class=\"card\">
        <h2>Популярные цели каталога</h2>
        <table>
          <thead>
            <tr><th>#</th><th>Цель</th><th>Продуктов</th></tr>
          </thead>
          <tbody>
            {goal_rows}
          </tbody>
        </table>
      </article>
    </section>

    <section class=\"card\">
      <h2>Последние заявки</h2>
      <table>
        <thead>
          <tr><th>Дата</th><th>Имя</th><th>Телефон</th><th>Квиз</th><th>План</th><th>Продукты</th></tr>
        </thead>
        <tbody>
          {lead_rows_html}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


async def _gather_dashboard_context() -> Dict[str, Any]:
    build = get_build_info()
    utm_metrics: Dict[growth_attribution.UtmKey, growth_attribution.UtmFunnelMetrics] = {}
    async with session_scope() as session:
        quiz_counts, quiz_total = await _collect_event_stats(session, "quiz_finish", "quiz")
        calc_counts, calc_total = await _collect_event_stats(session, "calc_finish", "calc")
        plans_total, products_counter = await _collect_plan_stats(session)
        leads_total, leads_recent, recent_leads = await _collect_lead_details(session)
        utm_metrics = await growth_attribution.collect_funnel_metrics(session)

    ctr = (plans_total / quiz_total * 100.0) if quiz_total else 0.0

    catalog_data = load_catalog()
    catalog_products = list(catalog_data["products"].values())
    catalog_total = len(catalog_products)
    goal_counter: Counter[str] = Counter()
    for product in catalog_products:
        for goal in product.get("goals", []) or []:
            goal_counter[str(goal)] += 1

    catalog_path = Path(__file__).resolve().parent / "catalog" / "products.json"
    try:
        updated = datetime.fromtimestamp(catalog_path.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        updated_str = "—"
    else:
        updated_str = updated.strftime("%Y-%m-%d")

    quiz_chart = _build_bar_chart("Завершено квизов", quiz_counts, "#2563eb")
    calc_chart = _build_bar_chart("Использование калькуляторов", calc_counts, "#ec4899")
    ctr_chart = _build_ctr_gauge(ctr)

    load_history = _load_load_history()
    load_chart = _build_load_chart(load_history)
    if load_history:
        latest_run = load_history[-1]
        latest_latency = latest_run.get("latency") if isinstance(latest_run, dict) else None
        p95_value = latest_latency.get("p95") if isinstance(latest_latency, dict) else None
        errors_value = latest_run.get("errors") if isinstance(latest_run, dict) else None
        timestamp_value = latest_run.get("timestamp") if isinstance(latest_run, dict) else None
        load_p95 = f"{p95_value:.0f} ms" if isinstance(p95_value, (int, float)) else "—"
        load_errors = str(errors_value) if isinstance(errors_value, int) else "—"
        load_timestamp = _format_dt(_parse_iso_timestamp(timestamp_value))
    else:
        load_p95 = "—"
        load_errors = "—"
        load_timestamp = "—"

    top_products = [(code, str(count)) for code, count in products_counter.most_common(10)]
    catalog_goals = [(goal, str(count)) for goal, count in goal_counter.most_common(10)]

    utm_sorted = growth_attribution.sort_metrics(utm_metrics, limit=6)
    utm_chart = _build_utm_chart(utm_sorted)
    utm_total = growth_attribution.summarize(utm_metrics)

    return {
        "quiz_chart": quiz_chart,
        "calc_chart": calc_chart,
        "ctr_chart": ctr_chart,
        "load_chart": load_chart,
        "utm_chart": utm_chart,
        "leads_total": leads_total,
        "leads_recent": leads_recent,
        "quiz_total": quiz_total,
        "calc_total": calc_total,
        "plans_total": plans_total,
        "ctr": ctr,
        "catalog_total": catalog_total,
        "catalog_updated": updated_str,
        "top_products": top_products,
        "catalog_goals": catalog_goals,
        "recent_leads": recent_leads,
        "load_p95": load_p95,
        "load_errors": load_errors,
        "load_timestamp": load_timestamp,
        "utm_total_reg": utm_total.registrations,
        "utm_ctr": utm_total.quiz_ctr,
        "utm_cr": utm_total.premium_cr,
        "build_info": build,
        "build_commit_short": build["commit"][:7] if build["commit"] not in {"unknown", ""} else build["commit"],
    }


def _extract_admin_name(request: Request) -> str:
    header = (request.headers.get("X-Admin") or "").strip()
    if not header:
        header = (request.query_params.get("admin") or "").strip()
    if not header:
        raise HTTPException(status_code=400, detail="Укажи администратора через X-Admin")
    if len(header) > 128:
        raise HTTPException(status_code=400, detail="Имя администратора слишком длинное")
    return header


def _auto_product_link(pid: str) -> str | None:
    base = (settings.BASE_PRODUCT_URL or "").strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/{quote(pid)}"


LINKS_PAGE_HTML = dedent("""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Управление ссылками</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    min-height: 100vh;
}
h1 {
    font-size: 1.5rem;
    margin: 0;
}
.page {
    max-width: 1080px;
    margin: 0 auto;
    padding: 32px 20px 64px;
}
.page__header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 16px;
    align-items: center;
    margin-bottom: 24px;
}
.header__admin {
    display: flex;
    flex-direction: column;
    gap: 6px;
}
label {
    font-size: 0.875rem;
    color: #94a3b8;
}
input[type="text"], select, textarea {
    background: #1e293b;
    border: 1px solid #334155;
    color: #e2e8f0;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.95rem;
}
input[type="text"]:focus, select:focus, textarea:focus {
    outline: 2px solid #38bdf8;
    outline-offset: 0;
}
.panel {
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.panel__row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    justify-content: space-between;
    align-items: center;
}
.set-selector {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
}
.panel__actions {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
}
.register-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}
.label {
    color: #94a3b8;
    margin-right: 6px;
}
.mono {
    font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
    font-size: 0.85rem;
    word-break: break-all;
}
.badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    margin-left: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.badge--muted {
    background: #1f2937;
    color: #94a3b8;
}
.badge--accent {
    background: #4ade80;
    color: #0f172a;
}
.btn {
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    background: #2563eb;
    color: #e2e8f0;
    font-size: 0.95rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: background 0.15s ease;
}
.btn.secondary {
    background: #1f2937;
    border-color: #334155;
}
.btn.icon {
    padding: 6px 10px;
    font-size: 1rem;
}
.btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}
.btn:not(:disabled):hover {
    background: #1d4ed8;
}
.btn.secondary:not(:disabled):hover {
    background: #273449;
}
.status {
    border-radius: 12px;
    padding: 10px 14px;
    margin-bottom: 20px;
    border: 1px solid transparent;
}
.status.hidden {
    display: none;
}
.status[data-kind="error"] {
    background: rgba(248, 113, 113, 0.15);
    border-color: rgba(248, 113, 113, 0.45);
    color: #fca5a5;
}
.status[data-kind="success"] {
    background: rgba(34, 197, 94, 0.15);
    border-color: rgba(34, 197, 94, 0.45);
    color: #86efac;
}
.status[data-kind="info"] {
    background: rgba(59, 130, 246, 0.12);
    border-color: rgba(59, 130, 246, 0.4);
    color: #93c5fd;
}
table.links-table {
    width: 100%;
    border-collapse: collapse;
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 16px;
    overflow: hidden;
}
table.links-table thead {
    background: #1f2937;
}
table.links-table th,
table.links-table td {
    padding: 12px 14px;
    text-align: left;
    border-bottom: 1px solid #1e293b;
    vertical-align: middle;
}
table.links-table tbody tr:last-child td {
    border-bottom: none;
}
.product-cell {
    min-width: 240px;
}
.product-title {
    font-weight: 600;
    margin-bottom: 4px;
}
.status-cell {
    width: 90px;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.04em;
    color: #94a3b8;
}
.truncate {
    max-width: 420px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.actions-cell {
    width: 120px;
    display: flex;
    gap: 8px;
}
.modal {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.75);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    z-index: 50;
}
.modal.hidden {
    display: none;
}
.modal__card {
    background: #0f172a;
    border: 1px solid #1f2937;
    border-radius: 16px;
    max-width: 520px;
    width: 100%;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.modal__card h2 {
    margin: 0;
    font-size: 1.25rem;
}
.modal__card p {
    margin: 0;
    color: #94a3b8;
    font-size: 0.9rem;
}
#import-text {
    min-height: 200px;
    resize: vertical;
}
.modal__actions {
    display: flex;
    gap: 12px;
    justify-content: flex-end;
}
@media (max-width: 720px) {
    .actions-cell {
        width: auto;
    }
    .truncate {
        max-width: 220px;
    }
    .set-selector {
        width: 100%;
    }
    .panel__actions {
        width: 100%;
        justify-content: flex-start;
    }
}
</style>
</head>
<body>
<div class="page">
    <div class="page__header">
        <h1>/links</h1>
        <div class="header__admin">
            <label for="admin-input">Администратор</label>
            <input id="admin-input" type="text" placeholder="Укажи имя" autocomplete="off" />
        </div>
    </div>
    <div class="panel">
        <div class="panel__row">
            <div class="set-selector">
                <span class="label">Активный сет:</span>
                <span id="active-set" class="badge badge--accent">—</span>
                <select id="set-select"></select>
                <button id="switch-set" class="btn">🔀 Переключить сет</button>
            </div>
            <div class="panel__actions">
                <button id="btn-import" class="btn secondary">📥 Импорт</button>
                <button id="btn-export" class="btn secondary">📤 Экспорт</button>
            </div>
        </div>
        <div class="register-row">
            <div>
                <span class="label">Регистрация:</span>
                <span id="register-link" class="mono">—</span>
                <span id="register-status" class="badge badge--muted">по умолчанию</span>
            </div>
            <div class="panel__actions">
                <button id="edit-register" class="btn">✏️ изменить</button>
                <button id="open-register" class="btn secondary">🔗 открыть</button>
            </div>
        </div>
    </div>
    <div id="status" class="status hidden" data-kind="info"></div>
    <table class="links-table">
        <thead>
            <tr>
                <th>Продукт</th>
                <th>Статус</th>
                <th>Ссылка</th>
                <th>Действия</th>
            </tr>
        </thead>
        <tbody id="products-body"></tbody>
    </table>
</div>
<div id="import-modal" class="modal hidden">
    <div class="modal__card">
        <h2>Импорт ссылок</h2>
        <p>Вставь JSON с ключами <code>register</code> и <code>products</code>. Текущие override будут заменены.</p>
        <textarea id="import-text" spellcheck="false" placeholder='{"register": "https://...", "products": {"id": "https://..."}}'></textarea>
        <div class="modal__actions">
            <button id="apply-import" class="btn">Применить</button>
            <button id="cancel-import" class="btn secondary">Отмена</button>
        </div>
    </div>
</div>
<script>
(() => {
    const state = {
        token: new URLSearchParams(window.location.search).get('token') || '',
        activeSet: '',
        register: '',
        registerOverride: null,
        sets: [],
        products: []
    };
    const dom = {
        admin: document.getElementById('admin-input'),
        activeSet: document.getElementById('active-set'),
        setSelect: document.getElementById('set-select'),
        registerLink: document.getElementById('register-link'),
        registerStatus: document.getElementById('register-status'),
        status: document.getElementById('status'),
        tableBody: document.getElementById('products-body'),
        importModal: document.getElementById('import-modal'),
        importText: document.getElementById('import-text')
    };

    dom.admin.value = localStorage.getItem('links-admin') || '';
    const persistAdmin = () => {
        localStorage.setItem('links-admin', dom.admin.value.trim());
    };
    dom.admin.addEventListener('change', persistAdmin);
    dom.admin.addEventListener('blur', persistAdmin);

    function buildUrl(path) {
        if (!state.token) {
            return path;
        }
        return path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(state.token);
    }

    async function fetchJson(path, options = {}) {
        const response = await fetch(buildUrl(path), options);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.detail || payload.error || 'Запрос завершился с ошибкой');
        }
        if (Object.prototype.hasOwnProperty.call(payload, 'ok') && !payload.ok) {
            throw new Error(payload.error || 'Запрос завершился с ошибкой');
        }
        return payload;
    }

    function showStatus(kind, message) {
        dom.status.textContent = message || '';
        dom.status.dataset.kind = kind || '';
        if (message) {
            dom.status.classList.remove('hidden');
        } else {
            dom.status.classList.add('hidden');
        }
    }

    function ensureAdmin() {
        const admin = dom.admin.value.trim();
        if (!admin) {
            showStatus('error', 'Укажи имя администратора перед изменениями');
            dom.admin.focus();
            throw new Error('missing-admin');
        }
        if (admin.length > 128) {
            showStatus('error', 'Имя администратора слишком длинное');
            throw new Error('invalid-admin');
        }
        return admin;
    }

    async function mutate(path, method, body) {
        const admin = ensureAdmin();
        const headers = {
            'Content-Type': 'application/json',
            'X-Admin': admin
        };
        const options = { method, headers };
        if (body !== undefined) {
            options.body = JSON.stringify(body);
        }
        const payload = await fetchJson(path, options);
        if (payload.message) {
            showStatus('success', payload.message);
        } else {
            showStatus('', '');
        }
        await loadState();
    }

    function render() {
        dom.activeSet.textContent = state.activeSet || '—';
        dom.registerLink.textContent = state.register || '—';
        if (state.registerOverride) {
            dom.registerStatus.textContent = 'override';
            dom.registerStatus.classList.remove('badge--muted');
            dom.registerStatus.classList.add('badge--accent');
        } else {
            dom.registerStatus.textContent = 'по умолчанию';
            dom.registerStatus.classList.add('badge--muted');
            dom.registerStatus.classList.remove('badge--accent');
        }

        dom.setSelect.innerHTML = '';
        state.sets.forEach((name) => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            if (name === state.activeSet) {
                option.selected = true;
            }
            dom.setSelect.appendChild(option);
        });

        renderProducts();
    }

    function renderProducts() {
        dom.tableBody.innerHTML = '';
        state.products.forEach((product) => {
            const tr = document.createElement('tr');

            const nameCell = document.createElement('td');
            nameCell.className = 'product-cell';
            const titleDiv = document.createElement('div');
            titleDiv.className = 'product-title';
            titleDiv.textContent = product.title || product.id;
            const idDiv = document.createElement('div');
            idDiv.className = 'mono';
            idDiv.textContent = product.id;
            nameCell.appendChild(titleDiv);
            nameCell.appendChild(idDiv);
            tr.appendChild(nameCell);

            const statusCell = document.createElement('td');
            statusCell.className = 'status-cell';
            statusCell.textContent = product.override ? 'override' : 'auto';
            tr.appendChild(statusCell);

            const linkCell = document.createElement('td');
            linkCell.className = 'mono truncate';
            const linkValue = product.override || product.link || '';
            linkCell.textContent = linkValue || '—';
            linkCell.title = linkValue;
            tr.appendChild(linkCell);

            const actionsCell = document.createElement('td');
            actionsCell.className = 'actions-cell';
            const editBtn = document.createElement('button');
            editBtn.className = 'btn icon';
            editBtn.type = 'button';
            editBtn.textContent = '✏️';
            editBtn.title = 'Изменить ссылку';
            editBtn.addEventListener('click', () => editProduct(product));
            actionsCell.appendChild(editBtn);

            const openBtn = document.createElement('button');
            openBtn.className = 'btn icon secondary';
            openBtn.type = 'button';
            openBtn.textContent = '🔗';
            openBtn.title = 'Открыть ссылку';
            openBtn.disabled = !product.link;
            openBtn.addEventListener('click', () => openProduct(product));
            actionsCell.appendChild(openBtn);

            tr.appendChild(actionsCell);
            dom.tableBody.appendChild(tr);
        });
    }

    async function loadState() {
        try {
            const payload = await fetchJson('/links/data');
            const data = payload.data || {};
            state.activeSet = data.active_set || '';
            state.register = data.register || '';
            state.registerOverride = data.register_override || null;
            state.sets = Array.isArray(data.sets) ? data.sets : [];
            state.products = Array.isArray(data.products) ? data.products : [];
            render();
        } catch (error) {
            const message = (error && error.message) ? error.message : 'Не удалось загрузить данные';
            showStatus('error', message);
        }
    }

    async function editRegister() {
        const current = state.registerOverride || state.register || '';
        const value = window.prompt('Новая ссылка регистрации (https://...)', current);
        if (value === null) {
            return;
        }
        const trimmed = value.trim();
        if (!trimmed) {
            showStatus('error', 'Ссылка не может быть пустой');
            return;
        }
        await mutate('/links/register', 'POST', { url: trimmed });
    }

    function openRegister() {
        if (!state.register) {
            showStatus('error', 'Нет активной ссылки регистрации');
            return;
        }
        window.open(state.register, '_blank', 'noopener');
    }

    async function editProduct(product) {
        const current = product.override || product.link || '';
        const value = window.prompt(`Ссылка для ${product.id}`, current);
        if (value === null) {
            return;
        }
        const trimmed = value.trim();
        if (!trimmed) {
            if (!product.override) {
                showStatus('info', 'Override не изменён');
                return;
            }
            if (!window.confirm(`Удалить override для ${product.id}?`)) {
                return;
            }
            await mutate('/links/product', 'DELETE', { product_id: product.id });
            return;
        }
        await mutate('/links/product', 'POST', { product_id: product.id, url: trimmed });
    }

    function openProduct(product) {
        if (!product.link) {
            showStatus('error', 'Для продукта нет ссылки');
            return;
        }
        window.open(product.link, '_blank', 'noopener');
    }

    function openImportModal() {
        dom.importText.value = '';
        dom.importModal.classList.remove('hidden');
        dom.importText.focus();
    }

    function closeImportModal() {
        dom.importModal.classList.add('hidden');
        dom.importText.value = '';
    }

    async function applyImport() {
        const raw = dom.importText.value.trim();
        if (!raw) {
            showStatus('error', 'Вставь JSON перед импортом');
            return;
        }
        let payload;
        try {
            payload = JSON.parse(raw);
        } catch (error) {
            showStatus('error', 'Невалидный JSON');
            return;
        }
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
            showStatus('error', 'Ожидался объект с ключами register/products');
            return;
        }
        if (!window.confirm('Применить импорт? Текущие override будут заменены.')) {
            return;
        }
        const body = {};
        if (typeof payload.register === 'string' && payload.register.trim()) {
            body.register = payload.register.trim();
        }
        if (payload.products && typeof payload.products === 'object') {
            body.products = payload.products;
        }
        await mutate('/links/import', 'POST', body);
        closeImportModal();
    }

    async function exportLinks() {
        try {
            const payload = await fetchJson('/links/export');
            const data = payload.data || {};
            const json = JSON.stringify(data, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const filename = `links-${state.activeSet || 'set'}.json`;
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            showStatus('success', 'Экспорт готов');
        } catch (error) {
            const message = (error && error.message) ? error.message : 'Не удалось экспортировать ссылки';
            showStatus('error', message);
        }
    }

    async function switchSet() {
        const target = dom.setSelect.value;
        if (!target || target === state.activeSet) {
            showStatus('info', 'Сет уже активен');
            return;
        }
        if (!window.confirm(`Переключить активный сет на ${target}?`)) {
            return;
        }
        await mutate('/links/switch', 'POST', { target });
    }

    document.getElementById('edit-register').addEventListener('click', editRegister);
    document.getElementById('open-register').addEventListener('click', openRegister);
    document.getElementById('btn-import').addEventListener('click', openImportModal);
    document.getElementById('btn-export').addEventListener('click', exportLinks);
    document.getElementById('switch-set').addEventListener('click', switchSet);
    document.getElementById('apply-import').addEventListener('click', applyImport);
    document.getElementById('cancel-import').addEventListener('click', () => {
        closeImportModal();
        showStatus('', '');
    });
    dom.importModal.addEventListener('click', (event) => {
        if (event.target === dom.importModal) {
            closeImportModal();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !dom.importModal.classList.contains('hidden')) {
            closeImportModal();
        }
    });

    loadState();
})();
</script>
</body>
</html>
""")


def _render_links_page() -> str:
    return LINKS_PAGE_HTML


async def _gather_links_state() -> Dict[str, Any]:
    register_effective = await get_register_link()
    export_payload = await export_set(None)
    register_override = None
    if isinstance(export_payload, dict):
        raw_register = export_payload.get("register")
        if isinstance(raw_register, str) and raw_register.strip():
            register_override = raw_register.strip()
    overrides = await get_all_product_links()
    active = export_payload.get("set") if isinstance(export_payload, dict) else None
    if not isinstance(active, str) or not active:
        active = await active_set_name()
    sets = await list_sets()
    catalog = load_catalog()
    ordered = catalog.get("ordered") if isinstance(catalog, dict) else None
    ordered_ids = list(ordered) if isinstance(ordered, list) else []
    products_meta: Dict[str, Dict[str, Any]] = {}
    raw_products = catalog.get("products") if isinstance(catalog, dict) else {}
    if isinstance(raw_products, dict):
        products_meta = raw_products  # type: ignore[assignment]
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _resolve_title(pid: str) -> str:
        meta = products_meta.get(pid) or {}
        if isinstance(meta, dict):
            for key in ("short_name", "title", "name"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return pid

    for pid in ordered_ids:
        seen.add(pid)
        override = overrides.get(pid)
        link = override or _auto_product_link(pid)
        rows.append(
            {
                "id": pid,
                "title": _resolve_title(pid),
                "override": override,
                "link": link,
            }
        )

    extra_ids = sorted(pid for pid in overrides if pid not in seen)
    for pid in extra_ids:
        override = overrides.get(pid)
        link = override or _auto_product_link(pid)
        rows.append(
            {
                "id": pid,
                "title": _resolve_title(pid),
                "override": override,
                "link": link,
            }
        )

    return {
        "register": register_effective,
        "register_override": register_override,
        "active_set": active,
        "sets": sets,
        "products": rows,
    }


@app.get("/links", response_class=HTMLResponse)
async def links_page(_: None = Depends(_require_token)) -> HTMLResponse:
    return HTMLResponse(_render_links_page())


@app.get("/links/data")
async def links_data(_: None = Depends(_require_token)) -> Dict[str, Any]:
    data = await _gather_links_state()
    return {"ok": True, "data": data}


@app.get("/links/export")
async def links_export(_: None = Depends(_require_token)) -> Dict[str, Any]:
    data = await export_set(None)
    return {"ok": True, "data": data}


@app.post("/links/register")
async def links_set_register(
    payload: RegisterUpdate,
    request: Request,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    admin = _extract_admin_name(request)
    try:
        with audit_actor(admin):
            await set_register_link(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": "Ссылка регистрации обновлена"}


@app.post("/links/product")
async def links_set_product(
    payload: ProductUpdate,
    request: Request,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    admin = _extract_admin_name(request)
    try:
        with audit_actor(admin):
            await set_product_link(payload.product_id, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": f"Override для {payload.product_id} сохранён"}


@app.delete("/links/product")
async def links_delete_product_override(
    payload: ProductDelete,
    request: Request,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    admin = _extract_admin_name(request)
    with audit_actor(admin):
        await delete_product_link(payload.product_id)
    return {"ok": True, "message": f"Override для {payload.product_id} удалён"}


@app.post("/links/import")
async def links_import(
    payload: ImportRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    admin = _extract_admin_name(request)
    try:
        with audit_actor(admin):
            if isinstance(payload.register, str) and payload.register.strip():
                await set_register_link(payload.register)
            if payload.products is not None:
                await set_bulk_links(payload.products)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": "Импорт применён"}


@app.post("/links/switch")
async def links_switch(
    payload: SwitchRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    admin = _extract_admin_name(request)
    try:
        with audit_actor(admin):
            await switch_set(payload.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": f"Активный сет переключён на {payload.target}"}


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(_: None = Depends(_require_token)) -> HTMLResponse:
    context = await _gather_dashboard_context()
    html = _render_dashboard_html(context)
    return HTMLResponse(html)
