import asyncio
import time
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram import Dispatcher
from aiohttp import web
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram,
                               generate_latest)


__all__ = [
    "MetricsMiddleware",
    "metrics_handler",
    "register_metrics",
    "setup_metrics",
]


_UPDATE_LATENCY = Histogram(
    "bot_update_latency_seconds",
    "Time spent processing Telegram updates.",
    labelnames=("update_type",),
)

_UPDATES_TOTAL = Counter(
    "bot_updates_total",
    "Total number of processed Telegram updates.",
    labelnames=("update_type",),
)

_UPDATE_ERRORS = Counter(
    "bot_update_errors_total",
    "Total number of update processing errors.",
    labelnames=("update_type",),
)

_ACTIVE_USERS_GAUGE = Gauge(
    "bot_active_users",
    "Number of users interacting with the bot during the rolling TTL window.",
)

_BOT_UPTIME = Gauge(
    "bot_uptime_seconds",
    "Bot uptime in seconds.",
)


class ActiveUsersTracker:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._users: Dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def mark_active(self, user_id: int) -> None:
        async with self._lock:
            now = time.monotonic()
            self._users[user_id] = now
            self._drop_expired(now)
            _ACTIVE_USERS_GAUGE.set(len(self._users))

    async def refresh(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._drop_expired(now)
            _ACTIVE_USERS_GAUGE.set(len(self._users))

    def _drop_expired(self, now: float) -> None:
        cutoff = now - self._ttl_seconds
        expired = [user_id for user_id, ts in self._users.items() if ts < cutoff]
        for user_id in expired:
            self._users.pop(user_id, None)


_active_users_tracker = ActiveUsersTracker()
_start_time = time.monotonic()
_uptime_task: asyncio.Task[Any] | None = None


async def _uptime_updater() -> None:
    while True:
        _BOT_UPTIME.set(time.monotonic() - _start_time)
        await asyncio.sleep(5)


class MetricsMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()

    async def __call__(self, handler, event, data):  # type: ignore[override]
        update_type = type(event).__name__
        _UPDATES_TOTAL.labels(update_type=update_type).inc()

        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None:
            # try to read from callback/message payloads
            message = getattr(event, "message", None)
            if message is not None:
                user = getattr(message, "from_user", None)
                user_id = getattr(user, "id", None)

        if isinstance(user_id, int):
            await _active_users_tracker.mark_active(user_id)

        started = time.perf_counter()
        try:
            return await handler(event, data)
        except Exception:
            _UPDATE_ERRORS.labels(update_type=update_type).inc()
            raise
        finally:
            elapsed = time.perf_counter() - started
            _UPDATE_LATENCY.labels(update_type=update_type).observe(elapsed)


async def metrics_handler(_: web.Request) -> web.Response:
    await _active_users_tracker.refresh()
    payload = generate_latest()
    return web.Response(body=payload, content_type=CONTENT_TYPE_LATEST)


def register_metrics(dp: Dispatcher) -> None:
    """Attach the metrics middleware and start uptime tracking."""
    global _uptime_task

    dp.update.middleware(MetricsMiddleware())
    if _uptime_task is None or _uptime_task.done():
        _uptime_task = asyncio.create_task(_uptime_updater())


def setup_metrics(web_app: web.Application) -> None:
    """Expose the Prometheus metrics endpoint."""
    web_app.router.add_get("/metrics", metrics_handler)
