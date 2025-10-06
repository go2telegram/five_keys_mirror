"""Streamlit UI for the global admin console."""
from __future__ import annotations

import json
import os
from textwrap import dedent

import httpx
import streamlit as st
from streamlit.components.v1 import html

BACKEND_URL = os.getenv("DASHBOARD_BACKEND_URL", "http://127.0.0.1:8700")
BACKEND_WS_URL = os.getenv("DASHBOARD_BACKEND_WS_URL", "ws://127.0.0.1:8700")
TELEGRAM_TOKEN_PARAM = "tg_token"


@st.cache_data(show_spinner=False)
def _fetch_initial_state(token: str) -> dict:
    with httpx.Client(timeout=5.0) as client:
        response = client.get(
            f"{BACKEND_URL}/dashboard/state",
            headers={"x-dashboard-token": token},
        )
        response.raise_for_status()
        return response.json()


def _require_authentication() -> str:
    params = st.experimental_get_query_params()
    provided_token = params.get(TELEGRAM_TOKEN_PARAM, [None])[0]

    if "auth_token" in st.session_state:
        provided_token = st.session_state["auth_token"]

    if not provided_token:
        st.error("Недостаточно прав. Авторизуйтесь через Telegram SSO ссылку.")
        st.stop()

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{BACKEND_URL}/auth/telegram",
                json={"token": provided_token},
            )
            response.raise_for_status()
            st.session_state["auth_token"] = provided_token
            st.session_state["auth_profile"] = response.json()
            return provided_token
    except httpx.HTTPStatusError:
        st.error("Авторизация не пройдена. Свяжитесь с internal-admins.")
        st.stop()
    except httpx.HTTPError as exc:  # pragma: no cover - defensive fallback
        st.error(f"Не удалось обратиться к backend: {exc}")
        st.stop()


st.set_page_config(
    page_title="Global Admin Console",
    page_icon="📊",
    layout="wide",
)

token = _require_authentication()
profile = st.session_state.get("auth_profile", {})
state = _fetch_initial_state(token)

st.sidebar.title("Global Dashboard")
st.sidebar.success(f"Authenticated as {profile.get('username', 'unknown')}")
st.sidebar.write("Веб-сокеты активны для живых обновлений.")

styles = dedent(
    """
    <style>
        :root {
            color-scheme: light dark;
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            grid-gap: 1.5rem;
        }
        .dashboard-card {
            background: var(--primary-background, rgba(255,255,255,0.85));
            padding: 1.5rem;
            border-radius: 16px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
        }
        .dashboard-card h2 {
            margin: 0 0 0.5rem 0;
            font-size: 1.4rem;
        }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            grid-gap: 0.75rem;
        }
        .kpi-item {
            padding: 0.75rem;
            border-radius: 12px;
            background: rgba(0,0,0,0.04);
        }
        .kpi-item strong {
            display: block;
            font-size: 0.9rem;
            color: rgba(0,0,0,0.6);
        }
        .kpi-item span {
            font-size: 1.4rem;
            font-weight: 600;
        }
        .logs {
            max-height: 400px;
            overflow-y: auto;
            font-family: var(--font, "SFMono-Regular", monospace);
        }
        .log-entry {
            margin-bottom: 0.75rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid rgba(0,0,0,0.05);
        }
        .log-entry span {
            display: inline-block;
            font-size: 0.8rem;
            margin-right: 0.5rem;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 0.35rem;
        }
    </style>
    """
)

component_html = f"""
{styles}
<div class="dashboard-grid" id="dashboard-root" data-token="{token}">
  <div class="dashboard-card" id="slo-card">
    <h2>Service Level Objectives</h2>
    <div class="kpi-grid" id="slo-kpis"></div>
  </div>
  <div class="dashboard-card" id="revenue-card">
    <h2>Revenue</h2>
    <div class="kpi-grid" id="revenue-kpis"></div>
  </div>
  <div class="dashboard-card" id="growth-card">
    <h2>Growth</h2>
    <div class="kpi-grid" id="growth-kpis"></div>
  </div>
  <div class="dashboard-card" id="experiments-card">
    <h2>Experiments</h2>
    <div class="kpi-grid" id="experiments-kpis"></div>
  </div>
  <div class="dashboard-card" id="logs-card" style="grid-column: 1 / span 2;">
    <h2>Operational Logs</h2>
    <div class="logs" id="logs"></div>
  </div>
</div>
<script>
(function() {{
  const initialState = {json.dumps(state)};
  const wsUrl = `{BACKEND_WS_URL}/ws/dashboard?token={token}`;
  const formatters = {{
    uptime_percent: (value) => `${{value.toFixed(2)}}%`,
    error_budget_remaining_percent: (value) => `${{value.toFixed(1)}}%`,
    latency_p95_ms: (value) => `${{value}} ms`,
    incidents_last_24h: (value) => `${{value}} incidents`,
    monthly_recurring_revenue: (value) => `$${{value.toLocaleString(undefined, {{maximumFractionDigits: 0}})}}`,
    pipeline_value: (value) => `$${{value.toLocaleString(undefined, {{maximumFractionDigits: 0}})}}`,
    arpu: (value) => `$${{value.toFixed(0)}}`,
    renewal_rate_percent: (value) => `${{value.toFixed(1)}}%`,
    new_signups: (value) => `${{value}} new`,
    activation_rate_percent: (value) => `${{value.toFixed(1)}}%`,
    churn_rate_percent: (value) => `${{value.toFixed(1)}}%`,
    nps: (value) => `${{value.toFixed(0)}}`,
    active: (value) => `${{value}} live`,
    completed_this_week: (value) => `${{value}} completed`,
    significant_wins: (value) => `${{value}} wins`,
    guardrail_alerts: (value) => `${{value}} alerts`,
  }};

  function renderKpis(containerId, data) {{
    const container = document.getElementById(containerId);
    container.innerHTML = Object.entries(data).map(([key, value]) => {{
      const formatter = formatters[key] || ((val) => val);
      const name = key.replace(/_/g, ' ').replace(/\b\w/g, chr => chr.toUpperCase());
      return `<div class="kpi-item"><strong>${{name}}</strong><span>${{formatter(value)}}</span></div>`;
    }}).join('');
  }}

  function renderLogs(logs) {{
    const container = document.getElementById('logs');
    container.innerHTML = logs.map((log) => {{
      const createdAt = new Date(log.created_at).toLocaleTimeString();
      const level = log.level.toUpperCase();
      const color = level === 'ERROR' ? '#ff4d4f' : (level === 'WARN' ? '#faad14' : '#1890ff');
      return `<div class="log-entry"><span>${{createdAt}}</span><span><span class="status-dot" style="background:${{color}}"></span>${{level}}</span><span>${{log.message}}</span></div>`;
    }}).join('');
  }}

  function render(state) {{
    renderKpis('slo-kpis', state.slo);
    renderKpis('revenue-kpis', state.revenue);
    renderKpis('growth-kpis', state.growth);
    renderKpis('experiments-kpis', state.experiments);
    renderLogs(state.logs);
  }}

  render(initialState);

  function connect() {{
    const socket = new WebSocket(wsUrl);
    socket.addEventListener('open', () => {{
      console.info('Dashboard websocket connected');
      socket.send('ready');
    }});
    socket.addEventListener('message', (event) => {{
      try {{
        const payload = JSON.parse(event.data);
        if (payload.payload) {{
          render(payload.payload);
        }}
      }} catch (err) {{
        console.error('Failed to parse dashboard payload', err);
      }}
    }});
    socket.addEventListener('close', () => {{
      console.warn('Dashboard websocket closed. Retrying in 3s');
      setTimeout(connect, 3000);
    }});
  }}

  connect();
}})();
</script>
"""

html(component_html, height=860, scrolling=True)
