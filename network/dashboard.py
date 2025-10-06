"""FastAPI application exposing the aggregated network dashboard."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .collector import NetworkCollector, NetworkNode


class NetworkNodeModel(BaseModel):
    name: str = Field(..., description="Display name of the node")
    base_url: str = Field(..., description="Base URL of the node, e.g. https://five-keys.example.com")
    latitude: float | None = Field(default=None, description="Latitude for map visualisation")
    longitude: float | None = Field(default=None, description="Longitude for map visualisation")
    region: str | None = Field(default=None, description="Optional region / city name")
    metrics_path: str = Field(default="/metrics", description="Override metrics path if different")

    def to_node(self) -> NetworkNode:
        return NetworkNode(**self.model_dump())


class NetworkSettings(BaseSettings):
    ENABLE_NETWORK_DASHBOARD: bool = False
    NETWORK_API_KEY: str | None = None
    NETWORK_REFRESH_SECONDS: int = 60
    NETWORK_NODE_TIMEOUT: float = 5.0
    NETWORK_NODES: list[NetworkNodeModel] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @field_validator("NETWORK_NODES", mode="before")
    @classmethod
    def _parse_nodes(cls, value: Any) -> Any:
        if isinstance(value, str):
            if not value.strip():
                return []
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:  # pragma: no cover - validation path
                raise ValueError("NETWORK_NODES must be valid JSON") from exc
        return value

    @model_validator(mode="after")
    def _validate_api_key(self) -> "NetworkSettings":
        if self.ENABLE_NETWORK_DASHBOARD and not self.NETWORK_API_KEY:
            raise ValueError("NETWORK_API_KEY must be set when ENABLE_NETWORK_DASHBOARD is true")
        return self

    @classmethod
    def load(cls) -> "NetworkSettings":
        try:
            return cls()
        except ValidationError as exc:  # pragma: no cover - surface nice error message
            errors = exc.errors(include_url=False)
            raise RuntimeError(f"Invalid network dashboard configuration: {errors}") from exc


settings = NetworkSettings.load()


def _ensure_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_query: str | None = Query(default=None, alias="api_key"),
) -> None:
    expected = settings.NETWORK_API_KEY
    if not settings.ENABLE_NETWORK_DASHBOARD:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network dashboard disabled")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NETWORK_API_KEY is not configured",
        )
    provided = x_api_key or api_key_query
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def create_app() -> FastAPI:
    router = APIRouter()

    nodes = [node.to_node() for node in settings.NETWORK_NODES]
    collector = NetworkCollector(
        nodes,
        refresh_interval=settings.NETWORK_REFRESH_SECONDS,
        request_timeout=settings.NETWORK_NODE_TIMEOUT,
    )

    @router.get("/network_admin", response_class=HTMLResponse)
    async def network_dashboard(_: None = Depends(_ensure_api_key)) -> HTMLResponse:
        snapshot = await collector.snapshot()
        html = _render_dashboard(snapshot)
        return HTMLResponse(content=html)

    @router.get("/network_admin/api/snapshot")
    async def snapshot(_: None = Depends(_ensure_api_key)) -> JSONResponse:
        snapshot_payload = await collector.snapshot()
        return JSONResponse(snapshot_payload)

    @router.post("/network_admin/api/refresh")
    async def refresh(_: None = Depends(_ensure_api_key)) -> JSONResponse:
        snapshot_payload = await collector.refresh()
        return JSONResponse(snapshot_payload)

    app = FastAPI(title="Five Keys Network Dashboard", docs_url=None, redoc_url=None)

    if settings.ENABLE_NETWORK_DASHBOARD:
        @app.on_event("startup")
        async def _startup() -> None:  # pragma: no cover - exercised at runtime
            await collector.start()

        @app.on_event("shutdown")
        async def _shutdown() -> None:  # pragma: no cover - exercised at runtime
            await collector.close()

    app.include_router(router)
    return app


def _render_dashboard(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary", {})
    generated_at = snapshot.get("generated_at")

    json_payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    html_template = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Five Keys — Network Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-VNyKQYQbMr2xE5m5wFfF1owhKp3v5l9I6GQ1hFjQf3s=" crossorigin="anonymous" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-o9N1j7kGEXG1/S1xYKBslZx0drfac+FZ6LJdP9HM+yo=" crossorigin="anonymous"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; background: #0b1d26; color: #f1f5f9; }}
    header {{ padding: 24px; background: #102a43; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4); }}
    h1 {{ margin: 0; font-size: 24px; }}
    main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding: 24px; }}
    @media (max-width: 1024px) {{
      main {{ grid-template-columns: 1fr; }}
    }}
    section {{ background: rgba(15, 32, 45, 0.85); border-radius: 16px; padding: 20px; box-shadow: 0 12px 30px rgba(8, 15, 30, 0.4); backdrop-filter: blur(12px); }}
    #map {{ height: 420px; border-radius: 12px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }}
    th, td {{ padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); text-align: left; }}
    tr:last-child td {{ border-bottom: none; }}
    .status-online {{ color: #4ade80; font-weight: 600; }}
    .status-offline {{ color: #f87171; font-weight: 600; }}
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 12px; }}
    .metric-card {{ padding: 12px; background: rgba(15,45,60,0.8); border-radius: 12px; box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.08); }}
    footer {{ padding: 16px 24px 24px; color: #94a3b8; font-size: 12px; }}
    .timestamp {{ color: #38bdf8; }}
  </style>
</head>
<body>
  <header>
    <h1>Сеть Five Keys</h1>
    <p>Онлайн: {online} · Оффлайн: {offline}</p>
  </header>
  <main>
    <section>
      <h2>Карта узлов</h2>
      <div id="map"></div>
    </section>
    <section>
      <h2>Сводные метрики</h2>
      <div class="metrics-grid" id="metrics"></div>
      <h2>Состояние узлов</h2>
      <table>
        <thead>
          <tr><th>Узел</th><th>Регион</th><th>Статус</th><th>Задержка (мс)</th></tr>
        </thead>
        <tbody id="nodes-table"></tbody>
      </table>
    </section>
  </main>
  <footer>
    Обновлено: <span class="timestamp">{generated}</span>
  </footer>
  <script id="network-data" type="application/json">{json_payload}</script>
  <script>
    const payload = JSON.parse(document.getElementById('network-data').textContent);
    const nodes = payload.nodes || [];

    const table = document.getElementById('nodes-table');
    if (!nodes.length) {{
      table.innerHTML = '<tr><td colspan="4">Узлы не подключены</td></tr>';
    }} else {{
      table.innerHTML = nodes.map(node => {{
        const statusClass = node.status === 'online' ? 'status-online' : 'status-offline';
        const latency = node.latency_ms !== null && node.latency_ms !== undefined ? Number(node.latency_ms).toFixed(2) : '—';
        return `<tr><td>${{node.name}}</td><td>${{node.region || '—'}}</td><td class="${{statusClass}}">${{node.status}}</td><td>${{latency}}</td></tr>`;
      }}).join('');
    }}

    const metricsContainer = document.getElementById('metrics');
    const metrics = payload.summary?.metrics || {{}};
    if (!Object.keys(metrics).length) {{
      metricsContainer.innerHTML = '<p>Нет числовых метрик</p>';
    }} else {{
      metricsContainer.innerHTML = Object.entries(metrics)
        .map(([key, values]) => `
          <div class="metric-card">
            <strong>${{key}}</strong>
            <div>avg: ${{values.avg}}</div>
            <div>max: ${{values.max}}</div>
            <div>min: ${{values.min}}</div>
          </div>
        `)
        .join('');
    }}

    const map = L.map('map', {{ zoomControl: false }});
    const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {{
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors'
    }});
    tiles.addTo(map);

    if (!nodes.length) {{
      map.setView([55.751244, 37.618423], 3);
    }} else {{
      const markers = [];
      nodes.forEach(node => {{
        if (node.latitude !== null && node.latitude !== undefined && node.longitude !== null && node.longitude !== undefined) {{
          const marker = L.marker([node.latitude, node.longitude]).addTo(map);
          marker.bindPopup(`<strong>${{node.name}}</strong><br/>${{node.region || ''}}<br/>Статус: ${{node.status}}`);
          markers.push(marker);
        }}
      }});
      if (markers.length) {{
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.25));
      }} else {{
        map.setView([55.751244, 37.618423], 3);
      }}
    }}
  </script>
</body>
</html>
"""
    return html_template.format(
        online=summary.get("online_nodes", 0),
        offline=summary.get("offline_nodes", 0),
        generated=generated_at or "—",
        json_payload=json_payload,
    )


app = create_app()

__all__ = ["create_app", "app", "NetworkSettings", "NetworkNodeModel"]
