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

from pydantic import BaseModel

from app.catalog.loader import load_catalog
from app.config import settings
from app.db.models import Event, Lead
from app.db.session import session_scope
from app.repo import events as events_repo, leads as leads_repo
from app.services import link_manager
from app.services.link_manager import LinkValidationError

app = FastAPI(title="Five Keys Admin Dashboard")


class LinkUpdatePayload(BaseModel):
    url: str | None = None


def _resolve_preview_chat_id() -> int | None:
    if settings.ADMIN_ID:
        return int(settings.ADMIN_ID)
    extra = settings.ADMIN_USER_IDS or []
    if isinstance(extra, (list, tuple, set)):
        for value in extra:
            if value:
                return int(value)
    return None


def _format_preview_message(set_title: str, product_title: str, product_id: str, url: str) -> str:
    parts = []
    title = (set_title or "").strip()
    if title:
        parts.append(f"Набор: {title}")
    parts.append(f"{product_title} ({product_id})")
    parts.append(url)
    return "\n".join(parts)


async def _send_link_preview_to_chat(
    chat_id: int, set_title: str, product_title: str, product_id: str, url: str
) -> None:
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не настроен")

    try:
        from aiogram import Bot
        from aiogram.exceptions import TelegramAPIError
    except ImportError as exc:  # pragma: no cover - defensive
        raise RuntimeError("aiogram недоступен") from exc

    message = _format_preview_message(set_title, product_title, product_id, url)

    try:
        async with Bot(token=settings.BOT_TOKEN) as bot:
            await bot.send_message(chat_id, message, disable_web_page_preview=False)
    except TelegramAPIError as exc:
        raise RuntimeError("Не удалось отправить ссылку в Telegram") from exc


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


def _render_links_html() -> str:
    return """<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <title>Five Keys · Управление ссылками</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\" />
  <style>
    body { font-family: 'Inter', Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; }
    main { max-width: 960px; margin: 0 auto; padding: 32px 24px 96px; display: flex; flex-direction: column; gap: 24px; }
    .page-header h1 { margin: 0 0 8px; font-size: 28px; font-weight: 600; }
    .page-header p { margin: 0; color: #94a3b8; }
    .card { background: #111827; border: 1px solid #1f2937; border-radius: 16px; padding: 20px 24px; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.35); }
    .card h2 { margin: 0 0 12px; font-size: 20px; font-weight: 600; color: #bfdbfe; }
    .muted { color: #64748b; font-size: 14px; }
    .set-controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-top: 12px; }
    label { font-size: 14px; color: #94a3b8; }
    select { background: #0f172a; color: #e2e8f0; border: 1px solid #1f2937; border-radius: 12px; padding: 8px 12px; min-width: 200px; font-size: 14px; }
    button { background: #2563eb; color: #f8fafc; border: none; border-radius: 12px; padding: 8px 16px; cursor: pointer; font-weight: 600; font-size: 14px; }
    button.ghost { background: transparent; border: 1px solid #1f2937; color: #93c5fd; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .inline-row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }
    .inline-form { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
    .inline-form input { flex: 1 1 260px; background: #0f172a; color: #e2e8f0; border: 1px solid #1f2937; border-radius: 12px; padding: 10px 14px; font-size: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #1f2937; font-size: 14px; }
    th { color: #93c5fd; text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; }
    tbody tr:hover td { background: rgba(37, 99, 235, 0.08); }
    .status { font-size: 20px; text-align: center; }
    .product-meta { display: flex; flex-direction: column; }
    .product-title { color: #64748b; font-size: 12px; margin-top: 4px; }
    .link-button { display: inline-flex; align-items: center; justify-content: center; padding: 8px 12px; border-radius: 12px; border: 1px solid #1f2937; color: #93c5fd; text-decoration: none; background: transparent; font-weight: 600; cursor: pointer; }
    .link-button[aria-disabled=\"true\"], .link-button:disabled { opacity: 0.45; pointer-events: none; }
    .editor-row td { background: rgba(37, 99, 235, 0.08); }
    .toast { position: fixed; bottom: 32px; right: 32px; background: rgba(15, 23, 42, 0.92); border: 1px solid #1f2937; border-radius: 12px; padding: 14px 18px; color: #e2e8f0; box-shadow: 0 20px 40px rgba(15, 23, 42, 0.45); opacity: 0; pointer-events: none; transition: opacity 0.25s ease; }
    .toast.show { opacity: 1; pointer-events: auto; }
    .toast.error { border-color: #f87171; color: #fecaca; }
    @media (max-width: 640px) {
      main { padding: 24px 16px 80px; }
      .inline-row { flex-direction: column; align-items: flex-start; }
      .inline-form { width: 100%; }
      .inline-form input { width: 100%; }
      select { width: 100%; }
      button { width: 100%; }
      .link-button { width: 100%; justify-content: center; }
    }
  </style>
</head>
<body>
  <main>
    <header class=\"page-header\">
      <h1>Управление ссылками</h1>
      <p>Активируй набор и правь ссылки без команд Telegram.</p>
    </header>

    <section class=\"card\">
      <h2>Наборы</h2>
      <p class=\"muted\" id=\"active-set-label\">Активный набор: —</p>
      <div class=\"set-controls\">
        <label for=\"set-select\">Выбери набор:</label>
        <select id=\"set-select\"></select>
        <button id=\"activate-button\" type=\"button\">Сделать активным</button>
      </div>
    </section>

    <section class=\"card\">
      <h2>Регистрация</h2>
      <div class=\"inline-row\">
        <span id=\"registration-url\" class=\"muted\">—</span>
        <div class=\"inline-row\" style=\"gap: 8px;\">
          <button id=\"registration-edit\" type=\"button\">✏️ Изменить</button>
          <a id=\"registration-open\" class=\"link-button\" href=\"#\" target=\"_blank\" rel=\"noopener\" aria-disabled=\"true\">🔗 Открыть</a>
        </div>
      </div>
      <div id=\"registration-form\" class=\"inline-form\" style=\"display:none;\">
        <input id=\"registration-input\" type=\"url\" placeholder=\"https://example.com\" />
        <button id=\"registration-save\" type=\"button\">✅ Сохранить</button>
        <button id=\"registration-cancel\" type=\"button\" class=\"ghost\">❌ Отмена</button>
      </div>
    </section>

    <section class=\"card\">
      <h2>Продукты</h2>
      <p class=\"muted\">Всего: <span id=\"product-count\">0</span></p>
      <table>
        <thead>
          <tr><th>ID</th><th>Статус</th><th>✏️</th><th>🔗</th></tr>
        </thead>
        <tbody id=\"products-body\"></tbody>
      </table>
    </section>
  </main>
  <div id=\"toast\" class=\"toast\"></div>

  <script>
    (function () {
      const params = new URLSearchParams(window.location.search);
      const token = params.get('token');

      const setSelect = document.getElementById('set-select');
      const activateButton = document.getElementById('activate-button');
      const activeSetLabel = document.getElementById('active-set-label');
      const registrationUrl = document.getElementById('registration-url');
      const registrationEdit = document.getElementById('registration-edit');
      const registrationForm = document.getElementById('registration-form');
      const registrationInput = document.getElementById('registration-input');
      const registrationSave = document.getElementById('registration-save');
      const registrationCancel = document.getElementById('registration-cancel');
      const registrationOpen = document.getElementById('registration-open');
      const productCount = document.getElementById('product-count');
      const productsBody = document.getElementById('products-body');
      const toast = document.getElementById('toast');

      let overview = null;
      let currentSet = null;
      let editorRow = null;
      const productRows = new Map();

      function showToast(message, isError) {
        toast.textContent = message;
        toast.classList.toggle('error', Boolean(isError));
        toast.classList.add('show');
        clearTimeout(showToast.timer);
        showToast.timer = setTimeout(() => {
          toast.classList.remove('show');
        }, 3200);
      }

      function buildUrl(path) {
        const url = new URL(path, window.location.origin);
        if (token) {
          url.searchParams.set('token', token);
        }
        return url;
      }

      async function apiFetch(path, options) {
        const opts = options ? { ...options } : {};
        const url = buildUrl(path);
        if (opts.body && !(opts.headers && opts.headers['Content-Type'])) {
          opts.headers = { ...(opts.headers || {}), 'Content-Type': 'application/json' };
        }
        const response = await fetch(url.toString(), opts);
        if (!response.ok) {
          let detail = 'Неизвестная ошибка';
          try {
            const payload = await response.json();
            if (payload && payload.detail) {
              detail = payload.detail;
            }
          } catch (err) {
            try {
              detail = await response.text();
            } catch (_) {
              detail = 'Ошибка запроса';
            }
          }
          throw new Error(detail || 'Ошибка запроса');
        }
        if (response.status === 204) {
          return null;
        }
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          return await response.json();
        }
        return await response.text();
      }

      function closeEditor() {
        if (editorRow) {
          editorRow.remove();
          editorRow = null;
        }
      }

      function updateActiveLabel() {
        if (!overview) {
          activeSetLabel.textContent = 'Активный набор: —';
          return;
        }
        const active = overview.sets.find((item) => item.id === overview.active_set_id);
        activeSetLabel.textContent = active ? `Активный набор: ${active.title}` : 'Активный набор: —';
      }

      function updateRegistrationView() {
        const url = currentSet && currentSet.registration_url ? currentSet.registration_url : '—';
        registrationUrl.textContent = url;
        const hasUrl = currentSet && Boolean(currentSet.registration_url);
        if (hasUrl) {
          registrationOpen.setAttribute('href', currentSet.registration_url);
          registrationOpen.setAttribute('aria-disabled', 'false');
        } else {
          registrationOpen.setAttribute('href', '#');
          registrationOpen.setAttribute('aria-disabled', 'true');
        }
      }

      function updateActivationState() {
        if (!overview || !currentSet) {
          activateButton.disabled = true;
          return;
        }
        activateButton.disabled = overview.active_set_id === currentSet.id;
      }

      function renderSetSelector() {
        if (!overview) {
          return;
        }
        setSelect.innerHTML = '';
        overview.sets.forEach((item) => {
          const option = document.createElement('option');
          option.value = String(item.id);
          option.textContent = item.title;
          if (currentSet && currentSet.id === item.id) {
            option.selected = true;
          }
          setSelect.appendChild(option);
        });
        updateActivationState();
        updateActiveLabel();
      }

      function updateProductRow(productId, url) {
        const meta = productRows.get(productId);
        if (!meta) {
          return;
        }
        meta.status.textContent = url ? '✅' : '➖';
        meta.open.disabled = !url;
      }

      function renderProducts() {
        productRows.clear();
        productsBody.innerHTML = '';
        if (!currentSet) {
          return;
        }
        currentSet.links.forEach((item) => {
          const row = document.createElement('tr');
          row.dataset.productId = item.product_id;

          const cellId = document.createElement('td');
          const meta = document.createElement('div');
          meta.className = 'product-meta';
          const code = document.createElement('span');
          code.textContent = item.product_id;
          const title = document.createElement('span');
          title.className = 'product-title';
          title.textContent = item.title;
          meta.appendChild(code);
          meta.appendChild(title);
          cellId.appendChild(meta);

          const cellStatus = document.createElement('td');
          cellStatus.className = 'status';

          const cellEdit = document.createElement('td');
          const editButton = document.createElement('button');
          editButton.type = 'button';
          editButton.textContent = '✏️';
          editButton.addEventListener('click', () => openProductEditor(row, item.product_id));
          cellEdit.appendChild(editButton);

          const cellLink = document.createElement('td');
          const openButton = document.createElement('button');
          openButton.type = 'button';
          openButton.className = 'link-button';
          openButton.textContent = '🔗';
          openButton.title = 'Отправить ссылку в чат';
          openButton.addEventListener('click', async () => {
            if (!currentSet || openButton.disabled) {
              return;
            }
            openButton.disabled = true;
            try {
              await apiFetch(`/links/api/sets/${currentSet.id}/links/${encodeURIComponent(item.product_id)}/preview`, {
                method: 'POST',
              });
              showToast('Ссылка отправлена в чат');
            } catch (error) {
              showToast(error.message, true);
            } finally {
              updateProductRow(item.product_id, item.url || null);
            }
          });
          cellLink.appendChild(openButton);

          row.appendChild(cellId);
          row.appendChild(cellStatus);
          row.appendChild(cellEdit);
          row.appendChild(cellLink);
          productsBody.appendChild(row);

          productRows.set(item.product_id, {
            row,
            status: cellStatus,
            open: openButton,
          });

          updateProductRow(item.product_id, item.url);
        });
      }

      function openProductEditor(row, productId) {
        if (!currentSet) {
          return;
        }
        closeEditor();
        const current = currentSet.links.find((item) => item.product_id === productId);
        const editor = document.createElement('tr');
        editor.className = 'editor-row';
        const cell = document.createElement('td');
        cell.colSpan = 4;
        const container = document.createElement('div');
        container.className = 'inline-form';
        const input = document.createElement('input');
        input.type = 'url';
        input.placeholder = 'https://example.com';
        input.value = current && current.url ? current.url : '';
        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.textContent = '✅ Сохранить';
        const cancelButton = document.createElement('button');
        cancelButton.type = 'button';
        cancelButton.textContent = '❌ Отмена';
        cancelButton.className = 'ghost';
        container.appendChild(input);
        container.appendChild(saveButton);
        container.appendChild(cancelButton);
        cell.appendChild(container);
        editor.appendChild(cell);
        row.after(editor);
        editorRow = editor;
        input.focus();

        input.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            saveButton.click();
          }
        });

        saveButton.addEventListener('click', async () => {
          try {
            const payload = { url: input.value };
            const result = await apiFetch(`/links/api/sets/${currentSet.id}/links/${encodeURIComponent(productId)}`, {
              method: 'POST',
              body: JSON.stringify(payload),
            });
            const target = currentSet.links.find((item) => item.product_id === productId);
            if (target) {
              target.url = result.url;
            }
            updateProductRow(productId, result.url);
            closeEditor();
            showToast('Ссылка сохранена');
          } catch (error) {
            showToast(error.message, true);
          }
        });

        cancelButton.addEventListener('click', () => {
          closeEditor();
        });
      }

      async function loadSet(setId) {
        try {
          currentSet = await apiFetch(`/links/api/sets/${setId}`);
          closeEditor();
          updateRegistrationView();
          renderProducts();
          renderSetSelector();
        } catch (error) {
          showToast(error.message, true);
        }
      }

      async function loadOverview() {
        try {
          overview = await apiFetch('/links/api/overview');
          productCount.textContent = overview.products.length;
          if (!overview.sets.length) {
            setSelect.innerHTML = '';
            activateButton.disabled = true;
            showToast('Нет доступных наборов', true);
            return;
          }
          const initialId = overview.active_set_id || overview.sets[0].id;
          await loadSet(initialId);
        } catch (error) {
          showToast(error.message, true);
        }
      }

      setSelect.addEventListener('change', async (event) => {
        const value = Number(event.target.value);
        if (Number.isFinite(value)) {
          await loadSet(value);
        }
      });

      activateButton.addEventListener('click', async () => {
        if (!overview || !currentSet) {
          return;
        }
        const active = overview.sets.find((item) => item.id === overview.active_set_id);
        const currentTitle = active ? active.title : '—';
        if (!window.confirm(`Ты меняешь активный набор c ${currentTitle} на ${currentSet.title} — продолжить?`)) {
          return;
        }
        try {
          const result = await apiFetch(`/links/api/sets/${currentSet.id}/activate`, { method: 'POST' });
          overview.active_set_id = result.active_set_id;
          overview.sets = overview.sets.map((item) => ({ ...item, is_active: item.id === result.active_set_id }));
          updateActivationState();
          updateActiveLabel();
          showToast('Набор активирован');
        } catch (error) {
          showToast(error.message, true);
        }
      });

      registrationEdit.addEventListener('click', () => {
        if (!currentSet) {
          return;
        }
        registrationForm.style.display = '';
        registrationInput.value = currentSet.registration_url || '';
        registrationInput.focus();
      });

      registrationCancel.addEventListener('click', () => {
        registrationForm.style.display = 'none';
        registrationInput.value = '';
      });

      registrationSave.addEventListener('click', async () => {
        if (!currentSet) {
          return;
        }
        try {
          const payload = { url: registrationInput.value };
          const result = await apiFetch(`/links/api/sets/${currentSet.id}/registration`, {
            method: 'POST',
            body: JSON.stringify(payload),
          });
          currentSet.registration_url = result.registration_url || null;
          updateRegistrationView();
          registrationForm.style.display = 'none';
          registrationInput.value = '';
          showToast('Ссылка сохранена');
        } catch (error) {
          showToast(error.message, true);
        }
      });

      registrationInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          registrationSave.click();
        } else if (event.key === 'Escape') {
          registrationCancel.click();
        }
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          closeEditor();
        }
      });

      loadOverview();
    })();
  </script>
</body>
</html>"""


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


@app.get("/links", response_class=HTMLResponse)
async def links_page(_: None = Depends(_require_token)) -> HTMLResponse:
    return HTMLResponse(_render_links_html())


@app.get("/links/api/overview")
async def links_overview(_: None = Depends(_require_token)) -> Dict[str, Any]:
    async with session_scope() as session:
        payload = await link_manager.list_sets_overview(session)
    return payload


@app.get("/links/api/sets/{set_id}")
async def links_set_details(set_id: int, _: None = Depends(_require_token)) -> Dict[str, Any]:
    async with session_scope() as session:
        payload = await link_manager.load_set_details(session, set_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Набор не найден")
    return payload


@app.post("/links/api/sets/{set_id}/activate")
async def links_activate_set(set_id: int, _: None = Depends(_require_token)) -> Dict[str, Any]:
    async with session_scope() as session:
        result = await link_manager.activate_set(session, set_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Набор не найден")
        await session.commit()
    return {"active_set_id": result["id"], "set": result}


@app.post("/links/api/sets/{set_id}/registration")
async def links_update_registration(
    set_id: int,
    payload: LinkUpdatePayload,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    async with session_scope() as session:
        try:
            result = await link_manager.save_registration_url(session, set_id, payload.url)
        except LinkValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Набор не найден")
        await session.commit()
    return result


@app.post("/links/api/sets/{set_id}/links/{product_id}")
async def links_update_product_link(
    set_id: int,
    product_id: str,
    payload: LinkUpdatePayload,
    _: None = Depends(_require_token),
) -> Dict[str, Any]:
    async with session_scope() as session:
        try:
            result = await link_manager.save_product_link(session, set_id, product_id, payload.url)
        except LinkValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()
    return result


@app.post("/links/api/sets/{set_id}/links/{product_id}/preview")
async def links_send_product_preview(
    set_id: int, product_id: str, _: None = Depends(_require_token)
) -> Dict[str, Any]:
    async with session_scope() as session:
        try:
            payload = await link_manager.prepare_link_preview(session, set_id, product_id)
        except LinkValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload is None:
        raise HTTPException(status_code=404, detail="Набор не найден")

    chat_id = _resolve_preview_chat_id()
    if chat_id is None:
        raise HTTPException(status_code=503, detail="Чат администратора не настроен")

    try:
        await _send_link_preview_to_chat(
            chat_id,
            payload["set"].get("title", ""),
            payload["product"].get("title", ""),
            payload["product"].get("id", ""),
            payload["url"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True}
