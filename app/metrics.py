from __future__ import annotations

import time

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


# Basic web server availability gauge that powers the smoke test and alerting rules.
_UP_GAUGE = Gauge("up", "Application availability")

# Request metrics that are consumed by SLO dashboards and alert rules.
_REQUEST_COUNTER = Counter(
    "http_requests_total",
    "HTTP requests processed by the aiohttp server",
    ("method", "path", "status"),
)
_REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ("method", "path"),
)


def mark_app_ready() -> None:
    """Mark the aiohttp application as ready for scraping."""

    _UP_GAUGE.set(1)


@web.middleware
async def metrics_middleware(request: web.Request, handler):
    """Collect request metrics for every non-metrics endpoint."""

    if request.path == "/metrics":
        return await handler(request)

    start = time.perf_counter()
    status_code = 500

    try:
        response = await handler(request)
        status_code = response.status
        return response
    except web.HTTPException as exc:
        status_code = exc.status
        raise
    finally:
        elapsed = time.perf_counter() - start
        _REQUEST_LATENCY.labels(request.method, request.path).observe(elapsed)
        _REQUEST_COUNTER.labels(request.method, request.path, str(status_code)).inc()


async def metrics_handler(_: web.Request) -> web.Response:
    """Expose Prometheus metrics for scraping."""

    payload = generate_latest()
    return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)

