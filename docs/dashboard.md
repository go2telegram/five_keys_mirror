# Global Admin Dashboard

The global dashboard provides a consolidated `/admin` control surface for
internal operators.  The solution combines a FastAPI backend (metrics,
websocket streaming, authentication) with a Streamlit-driven UI.

## Getting started locally

```bash
python dashboard/app.py
```

This command starts both services:

- FastAPI backend on `http://127.0.0.1:8700`
- Streamlit UI on `http://localhost:8500/admin`

Open the UI with the internal Telegram SSO token appended as a query
parameter, e.g. `http://localhost:8500/admin?tg_token=demo-admin-token`.

## Live data refresh

The page establishes a WebSocket connection to `ws://127.0.0.1:8700/ws/dashboard`
and receives live KPI payloads (SLO, revenue, growth, experiments and log
streams).  Metrics are also exposed on `/metrics` for Prometheus scraping.

## Feature flags and rollback

The dashboard is guarded by the `ENABLE_GLOBAL_DASHBOARD` flag.  To disable the
feature entirely set `ENABLE_GLOBAL_DASHBOARD=false` before launching the
application.  This is also the recommended rollback procedure.

## Deployment

An example Nginx location block is available in `deploy/nginx.conf`.  It proxies
`/admin` traffic to the Streamlit process and `/ws/dashboard` to the FastAPI
backend while keeping the rest of the bot routing unchanged.
