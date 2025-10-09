"""FastAPI-powered admin dashboard for analytics."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import plotly.graph_objects as go
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from plotly.io import to_html
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.loader import load_catalog
from app.config import settings
from app.db.models import Event, Lead
from app.db.session import session_scope
from app.repo import events as events_repo, leads as leads_repo

app = FastAPI(title="Five Keys Admin Dashboard")


def _require_token(request: Request) -> None:
    token = settings.DASHBOARD_TOKEN
    if not token:
        raise HTTPException(status_code=503, detail="Dashboard token is not configured")

    provided: str | None = None
    header = request.headers.get("Authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer":
            provided = value.strip()
        else:
            provided = header.strip()
    if provided is None:
        provided = request.query_params.get("token")

    if provided != token:
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    fig.update_layout(height=320, margin=dict(l=40, r=40, t=60, b=40), paper_bgcolor="#0f172a", font=dict(color="#e2e8f0"))
    return to_html(fig, include_plotlyjs=False, full_html=False)


def _format_dt(dt: datetime | None) -> str:
    if not isinstance(dt, datetime):
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _render_table(rows: List[Tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td>{idx + 1}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>"
        for idx, cells in enumerate(rows)
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
    top_products_rows = _render_table(context["top_products"])
    goal_rows = _render_table(context["catalog_goals"])
    lead_rows_html = "".join(
        "<tr>"
        f"<td>{_format_dt(row['created_at'])}</td>"
        f"<td>{row['name']}</td>"
        f"<td>{row['phone']}</td>"
        f"<td>{row['quiz'] or '—'}</td>"
        f"<td>{row['plan'] or '—'}</td>"
        f"<td>{row['products'] or '—'}</td>"
        "</tr>"
        for row in context["recent_leads"]
    ) or "<tr><td colspan='6' class='muted'>Нет заявок</td></tr>"

    plotly_script = "<script src=\"https://cdn.plot.ly/plotly-latest.min.js\"></script>"

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
  </header>
  <main>
    <section class=\"cards\">
      <article class=\"card\">
        <h2>Лиды всего</h2>
        <div class=\"metric\">{context['leads_total']}</div>
        <p class=\"muted\">За 7 дней: {context['leads_recent']}</p>
      </article>
      <article class=\"card\">
        <h2>Завершено квизов</h2>
        <div class=\"metric\">{context['quiz_total']}</div>
      </article>
      <article class=\"card\">
        <h2>Калькуляторы</h2>
        <div class=\"metric\">{context['calc_total']}</div>
      </article>
      <article class=\"card\">
        <h2>Планы рекомендаций</h2>
        <div class=\"metric\">{context['plans_total']}</div>
      </article>
      <article class=\"card\">
        <h2>CTR (квиз → план)</h2>
        <div class=\"metric\">{context['ctr']:.2f}%</div>
      </article>
      <article class=\"card\">
        <h2>Каталог</h2>
        <div class=\"metric\">{context['catalog_total']} SKU</div>
        <p class=\"muted\">Обновлено: {context['catalog_updated']}</p>
      </article>
      <article class=\"card\">
        <h2>Нагрузочный тест P95</h2>
        <div class=\"metric\">{context['load_p95']}</div>
        <p class=\"muted\">Ошибки: {context['load_errors']} · {context['load_timestamp']}</p>
      </article>
    </section>

    <section class=\"charts\">
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
    async with session_scope() as session:
        quiz_counts, quiz_total = await _collect_event_stats(session, "quiz_finish", "quiz")
        calc_counts, calc_total = await _collect_event_stats(session, "calc_finish", "calc")
        plans_total, products_counter = await _collect_plan_stats(session)
        leads_total, leads_recent, recent_leads = await _collect_lead_details(session)

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

    return {
        "quiz_chart": quiz_chart,
        "calc_chart": calc_chart,
        "ctr_chart": ctr_chart,
        "load_chart": load_chart,
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
    }


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(_: None = Depends(_require_token)) -> HTMLResponse:
    context = await _gather_dashboard_context()
    html = _render_dashboard_html(context)
    return HTMLResponse(html)
