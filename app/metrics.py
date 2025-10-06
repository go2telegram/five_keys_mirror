from __future__ import annotations

from aiohttp import web
from prometheus_client import Gauge, CONTENT_TYPE_LATEST, generate_latest

ANOMALY_ACTIVE = Gauge(
    "anomaly_active",
    "Flag indicating active anomaly detection for a metric window",
    labelnames=("kind",),
)


async def metrics_handler(_: web.Request) -> web.Response:
    payload = generate_latest()
    return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)
