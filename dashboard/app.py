"""Entry point for the global admin dashboard service.

This module bootstraps a FastAPI backend that feeds KPI data over a
WebSocket channel and serves auxiliary HTTP endpoints.  A Streamlit
process hosts the interactive UI under `/admin`.

Run locally with:

```
python dashboard/app.py
```
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

ENABLE_GLOBAL_DASHBOARD = (
    os.getenv("ENABLE_GLOBAL_DASHBOARD", "true").lower() not in {"0", "false", "off"}
)
STREAMLIT_PORT = int(os.getenv("GLOBAL_DASHBOARD_PORT", "8500"))
STREAMLIT_BASE_PATH = os.getenv("GLOBAL_DASHBOARD_BASE_PATH", "admin")
BACKEND_PORT = int(os.getenv("GLOBAL_DASHBOARD_BACKEND_PORT", "8700"))
TELEGRAM_OAUTH_TOKEN = os.getenv("TELEGRAM_OAUTH_TOKEN", "demo-admin-token")


def _ensure_enabled() -> None:
    if ENABLE_GLOBAL_DASHBOARD:
        return
    raise SystemExit(
        "Global dashboard disabled. Set ENABLE_GLOBAL_DASHBOARD=true to run the console."
    )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class SLOPayload(BaseModel):
    uptime_percent: float
    error_budget_remaining_percent: float
    latency_p95_ms: int
    incidents_last_24h: int


class RevenuePayload(BaseModel):
    monthly_recurring_revenue: float
    pipeline_value: float
    arpu: float
    renewal_rate_percent: float


class GrowthPayload(BaseModel):
    new_signups: int
    activation_rate_percent: float
    churn_rate_percent: float
    nps: float


class ExperimentsPayload(BaseModel):
    active: int
    completed_this_week: int
    significant_wins: int
    guardrail_alerts: int


class LogEntry(BaseModel):
    level: str
    message: str
    created_at: datetime


class DashboardState(BaseModel):
    generated_at: datetime
    slo: SLOPayload
    revenue: RevenuePayload
    growth: GrowthPayload
    experiments: ExperimentsPayload
    logs: List[LogEntry]


@dataclass
class DashboardBroker:
    """Coordinates state distribution across websocket clients."""

    _connections: Set[WebSocket] = field(default_factory=set)
    _state: Optional[DashboardState] = None
    _log_limit: int = 50
    _update_task: Optional[asyncio.Task[None]] = None

    async def startup(self) -> None:
        if self._update_task and not self._update_task.done():
            return
        self._state = self._state or self._generate_initial_state()
        self._update_task = asyncio.create_task(self._autorefresh_loop())

    async def shutdown(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task
        await self._close_all()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        if self._state:
            await websocket.send_json({"type": "snapshot", "payload": json.loads(self._state.model_dump_json())})

    async def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        if not self._connections:
            return
        stale: List[WebSocket] = []
        for connection in list(self._connections):
            try:
                await connection.send_json(payload)
            except WebSocketDisconnect:
                stale.append(connection)
        for connection in stale:
            self._connections.discard(connection)

    def state(self) -> DashboardState:
        assert self._state is not None
        return self._state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _close_all(self) -> None:
        for connection in list(self._connections):
            try:
                await connection.close()
            finally:
                self._connections.discard(connection)

    async def _autorefresh_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(5)
                self._apply_random_mutations()
                await self.broadcast(
                    {
                        "type": "update",
                        "payload": json.loads(self._state.model_dump_json()),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
        except asyncio.CancelledError:
            raise

    def _apply_random_mutations(self) -> None:
        import random

        state = self.state()
        state.generated_at = datetime.utcnow()

        slo = state.slo
        slo.latency_p95_ms = max(80, int(random.gauss(mu=slo.latency_p95_ms, sigma=10)))
        slo.uptime_percent = min(100.0, max(95.0, random.gauss(mu=99.6, sigma=0.1)))
        slo.error_budget_remaining_percent = min(
            100.0, max(70.0, random.gauss(mu=slo.error_budget_remaining_percent, sigma=1.5))
        )
        slo.incidents_last_24h = max(0, int(random.random() < 0.05))

        revenue = state.revenue
        revenue.monthly_recurring_revenue = max(
            0.0, revenue.monthly_recurring_revenue + random.uniform(-5_000, 15_000)
        )
        revenue.pipeline_value = max(0.0, revenue.pipeline_value + random.uniform(-3_000, 12_000))
        revenue.arpu = max(10.0, revenue.arpu + random.uniform(-1.0, 1.5))
        revenue.renewal_rate_percent = min(
            100.0, max(75.0, random.gauss(mu=revenue.renewal_rate_percent, sigma=1.0))
        )

        growth = state.growth
        growth.new_signups = max(0, growth.new_signups + int(random.uniform(-10, 35)))
        growth.activation_rate_percent = min(
            100.0, max(30.0, random.gauss(mu=growth.activation_rate_percent, sigma=1.5))
        )
        growth.churn_rate_percent = min(
            30.0, max(1.0, random.gauss(mu=growth.churn_rate_percent, sigma=0.4))
        )
        growth.nps = min(100.0, max(-100.0, random.gauss(mu=growth.nps, sigma=1.0)))

        experiments = state.experiments
        experiments.active = max(0, experiments.active + int(random.uniform(-1, 1)))
        experiments.completed_this_week = max(
            0, experiments.completed_this_week + int(random.uniform(-1, 2))
        )
        experiments.significant_wins = max(
            0, experiments.significant_wins + int(random.random() < 0.3)
        )
        experiments.guardrail_alerts = max(
            0, experiments.guardrail_alerts + int(random.random() < 0.1) - int(random.random() < 0.2)
        )

        if random.random() < 0.4:
            self._append_log_entry(
                level=random.choice(["INFO", "WARN", "ERROR"]),
                message=random.choice(
                    [
                        "Deployment completed",
                        "New revenue milestone reached",
                        "Guardrail breach auto-resolved",
                        "Background sync retrying",
                        "Anomaly detected in churn cohort",
                    ]
                ),
            )

    def _append_log_entry(self, *, level: str, message: str) -> None:
        state = self.state()
        logs = list(state.logs)
        logs.insert(
            0,
            LogEntry(level=level, message=message, created_at=datetime.utcnow()),
        )
        state.logs = logs[: self._log_limit]

    def _generate_initial_state(self) -> DashboardState:
        now = datetime.utcnow()
        return DashboardState(
            generated_at=now,
            slo=SLOPayload(
                uptime_percent=99.6,
                error_budget_remaining_percent=88.0,
                latency_p95_ms=120,
                incidents_last_24h=0,
            ),
            revenue=RevenuePayload(
                monthly_recurring_revenue=320_000.0,
                pipeline_value=890_000.0,
                arpu=240.0,
                renewal_rate_percent=93.0,
            ),
            growth=GrowthPayload(
                new_signups=860,
                activation_rate_percent=42.0,
                churn_rate_percent=4.2,
                nps=56.0,
            ),
            experiments=ExperimentsPayload(
                active=7,
                completed_this_week=5,
                significant_wins=2,
                guardrail_alerts=1,
            ),
            logs=[
                LogEntry(level="INFO", message="Dashboard bootstrapped", created_at=now),
            ],
        )


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

broker = DashboardBroker()
app = FastAPI(title="Global Admin Console", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    await broker.startup()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await broker.shutdown()


@app.get("/version")
async def version() -> Dict[str, str]:
    return {"service": "global-dashboard", "version": app.version}


@app.get("/ping")
async def ping() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    state = broker.state()
    return "\n".join(
        [
            "# HELP dashboard_latency_p95_ms 95th percentile latency",
            "# TYPE dashboard_latency_p95_ms gauge",
            f"dashboard_latency_p95_ms {state.slo.latency_p95_ms}",
            "# HELP dashboard_mrr Monthly recurring revenue",
            "# TYPE dashboard_mrr gauge",
            f"dashboard_mrr {state.revenue.monthly_recurring_revenue}",
            "# HELP dashboard_activation_rate Activation rate percentage",
            "# TYPE dashboard_activation_rate gauge",
            f"dashboard_activation_rate {state.growth.activation_rate_percent}",
        ]
    )


@app.post("/auth/telegram")
async def telegram_auth(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = payload.get("token")
    if not token or token != TELEGRAM_OAUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {"username": "internal-admin", "scopes": ["dashboard:read"]}


@app.get("/dashboard/state")
async def dashboard_state(x_dashboard_token: str | None = Header(default=None)) -> DashboardState:
    if x_dashboard_token != TELEGRAM_OAUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    return broker.state()


@app.websocket("/ws/dashboard")
async def dashboard_stream(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token != TELEGRAM_OAUTH_TOKEN:
        await websocket.close(code=4401)
        return
    await broker.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broker.disconnect(websocket)


# ---------------------------------------------------------------------------
# Bootstrap logic
# ---------------------------------------------------------------------------


async def _serve() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=BACKEND_PORT, log_level="info")
    server = uvicorn.Server(config)

    streamlit_script = os.path.join(os.path.dirname(__file__), "ui", "main.py")
    env = os.environ.copy()
    env.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    env.setdefault("DASHBOARD_BACKEND_URL", f"http://127.0.0.1:{BACKEND_PORT}")
    env.setdefault("DASHBOARD_BACKEND_WS_URL", f"ws://127.0.0.1:{BACKEND_PORT}")
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

    streamlit_cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        streamlit_script,
        f"--server.port={STREAMLIT_PORT}",
        f"--server.baseUrlPath={STREAMLIT_BASE_PATH}",
        "--server.enableCORS=false",
        "--server.headless=true",
    ]
    streamlit_proc = subprocess.Popen(streamlit_cmd, env=env)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        server.should_exit = True
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # add_signal_handler is not available on Windows event loops. Fallback to default.
            signal.signal(sig, lambda *_: _signal_handler())

    async def _watch_streamlit() -> None:
        while not stop_event.is_set():
            if streamlit_proc.poll() is not None:
                server.should_exit = True
                stop_event.set()
                break
            await asyncio.sleep(1)

    try:
        await asyncio.gather(server.serve(), _watch_streamlit())
    finally:
        stop_event.set()
        if streamlit_proc.poll() is None:
            streamlit_proc.terminate()
            try:
                await asyncio.to_thread(streamlit_proc.wait, timeout=5)
            except subprocess.TimeoutExpired:
                streamlit_proc.kill()


def main() -> None:
    _ensure_enabled()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
