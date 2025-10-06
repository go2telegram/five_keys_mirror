"""Profiling middleware that exposes Prometheus metrics for handler latency."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest

DEFAULT_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
)

handler_latency = Histogram(
    "handler_latency_seconds",
    "Latency of processed handlers in seconds.",
    labelnames=("route",),
    buckets=DEFAULT_LATENCY_BUCKETS,
)


def _resolve_handler_name(handler: Callable[..., Awaitable[Any]], data: Dict[str, Any]) -> str:
    """Try to provide a stable name for the handled route."""
    callback = data.get("handler")
    if callback is not None:
        module = getattr(callback, "__module__", "")
        qualname = getattr(callback, "__qualname__", "")
        if module or qualname:
            return f"{module}.{qualname}".strip(".")

    module = getattr(handler, "__module__", "")
    qualname = getattr(handler, "__qualname__", "")
    if module or qualname:
        return f"{module}.{qualname}".strip(".")

    event = data.get("event")
    if event is not None:
        return event.__class__.__name__

    return getattr(handler, "__name__", "unknown")


class ProfilerMiddleware(BaseMiddleware):
    """Collect latency histogram for every handler invocation."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        route = _resolve_handler_name(handler, data)
        start = time.perf_counter()
        try:
            return await handler(event, data)
        finally:
            duration = time.perf_counter() - start
            handler_latency.labels(route=route).observe(duration)


async def metrics_handler(_: web.Request) -> web.Response:
    """Expose collected Prometheus metrics."""

    payload = generate_latest()
    return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)
