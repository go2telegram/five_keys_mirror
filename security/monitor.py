"""Runtime security monitor for anomaly and intrusion detection.

This module provides light‑weight heuristics for detecting suspicious
behaviour around the webhook HTTP server.  The goal is not to replace a real
IDS but to surface potentially malicious activity to the bot operator.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Optional

from aiohttp import web

logger = logging.getLogger(__name__)


SUSPICIOUS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\.\.\/",  # directory traversal
        r"(<|%3C)script",  # xss
        r"union\s+select",
        r"sleep\(\d+\)",
        r"\bselect\b.*\bfrom\b",
        r"\binformation_schema\b",
        r"\bdrop\s+table",
        r"or\s+1=1",
    )
)


@dataclass(slots=True)
class SecurityEvent:
    """Structured representation of a security relevant event."""

    timestamp: float
    event_type: str
    description: str
    severity: str = "medium"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "description": self.description,
            "severity": self.severity,
            "metadata": self.metadata,
        }


class SecurityMonitor:
    """Tracks suspicious behaviour and exposes aggregated status."""

    def __init__(
        self,
        *,
        retention_limit: int = 200,
        rate_limit_threshold: int = 25,
        rate_limit_window: int = 60,
    ) -> None:
        self._enabled = True
        self._events: Deque[SecurityEvent] = deque(maxlen=retention_limit)
        self._lock = asyncio.Lock()
        self._event_counters: Counter[str] = Counter()
        self._request_total = 0
        self._unique_sources: set[str] = set()
        self._rate_limit_threshold = rate_limit_threshold
        self._rate_limit_window = rate_limit_window
        self._requests_per_ip: Dict[str, Deque[float]] = defaultdict(deque)
        self._allowed_paths: set[str] = set()

    # ------------------------------------------------------------------
    # configuration
    def configure(self, *, enabled: bool | None = None, allowed_paths: Iterable[str] | None = None) -> None:
        if enabled is not None:
            self._enabled = bool(enabled)
        if allowed_paths:
            self._allowed_paths.update(allowed_paths)

    # ------------------------------------------------------------------
    async def log_event(
        self,
        event_type: str,
        description: str,
        *,
        severity: str = "medium",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._enabled:
            return
        metadata = metadata or {}
        evt = SecurityEvent(
            timestamp=time.time(),
            event_type=event_type,
            description=description,
            severity=severity,
            metadata=metadata,
        )
        async with self._lock:
            self._events.appendleft(evt)
            self._event_counters[event_type] += 1

    # ------------------------------------------------------------------
    def ingest_log_record(self, level: str, message: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Naive log analyser that maps concerning log lines into events."""
        if not self._enabled:
            return
        lower_msg = message.lower()
        metadata = metadata or {}
        if "unauthorised" in lower_msg or "unauthorized" in lower_msg:
            asyncio.create_task(
                self.log_event(
                    "intrusion_attempt",
                    "Лог зафиксировал попытку несанкционированного доступа.",
                    severity="high",
                    metadata={"source": metadata.get("source"), "log": message},
                )
            )
        elif "error" in level.lower() and ("sql" in lower_msg or "traceback" in lower_msg):
            asyncio.create_task(
                self.log_event(
                    "anomaly",
                    "Необычная ошибка в логах приложения.",
                    severity="medium",
                    metadata={"log": message},
                )
            )

    # ------------------------------------------------------------------
    async def record_request(
        self,
        *,
        path: str,
        method: str,
        status: int,
        source_ip: str | None,
        user_agent: str | None = None,
        query: str | None = None,
        response_time: float | None = None,
    ) -> None:
        if not self._enabled:
            return

        ip = source_ip or "unknown"
        user_agent = (user_agent or "").lower()
        now = time.time()
        is_allowed = path in self._allowed_paths

        async with self._lock:
            self._request_total += 1
            self._unique_sources.add(ip)

        # rate limiting per IP
        ip_queue = self._requests_per_ip[ip]
        ip_queue.append(now)
        while ip_queue and now - ip_queue[0] > self._rate_limit_window:
            ip_queue.popleft()

        if len(ip_queue) > self._rate_limit_threshold:
            await self.log_event(
                "suspicious_traffic",
                "Замечен всплеск запросов от одного IP.",
                severity="medium",
                metadata={"ip": ip, "count": len(ip_queue), "window": self._rate_limit_window},
            )

        if user_agent and ("sqlmap" in user_agent or "crawler" in user_agent):
            await self.log_event(
                "suspicious_traffic",
                "Запрос выполнен клиентом с известным сигнатурным User-Agent.",
                severity="medium",
                metadata={"ip": ip, "user_agent": user_agent},
            )

        # suspicious patterns in url/query
        combined = f"{path}?{query}" if query else path
        for pattern in SUSPICIOUS_PATTERNS:
            if pattern.search(combined):
                await self.log_event(
                    "intrusion_attempt",
                    "Замечен подозрительный запрос (паттерн атаки).",
                    severity="high",
                    metadata={"ip": ip, "pattern": pattern.pattern, "path": path, "query": query},
                )
                break

        if not is_allowed and status in {401, 403, 404}:
            await self.log_event(
                "intrusion_attempt",
                "Запрос к неразрешённому endpoint.",
                severity="medium",
                metadata={"ip": ip, "path": path, "status": status},
            )

        if status >= 500:
            await self.log_event(
                "anomaly",
                "Сервис ответил ошибкой 5xx.",
                severity="medium",
                metadata={"path": path, "status": status},
            )

        if response_time and response_time > 3:
            await self.log_event(
                "anomaly",
                "Долгий ответ сервиса может указывать на атаку.",
                severity="low",
                metadata={"path": path, "duration": response_time},
            )

        # Check if IP is private but request came externally (we treat as anomaly)
        try:
            if ip != "unknown" and not ipaddress.ip_address(ip).is_global:
                await self.log_event(
                    "anomaly",
                    "Получен запрос с нестандартного приватного адреса.",
                    severity="low",
                    metadata={"ip": ip, "path": path},
                )
        except ValueError:
            # malformed IP
            await self.log_event(
                "suspicious_traffic",
                "Не удалось разобрать IP отправителя.",
                severity="low",
                metadata={"ip": ip, "path": path},
            )

    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of counters and recent events."""
        events = list(self._events)[:10]
        return {
            "enabled": self._enabled,
            "total_requests": self._request_total,
            "unique_sources": len(self._unique_sources),
            "event_counters": dict(self._event_counters),
            "recent_events": [evt.as_dict() for evt in events],
            "timestamp": time.time(),
        }


security_monitor = SecurityMonitor()


@web.middleware
async def security_middleware(request: web.Request, handler):  # type: ignore[override]
    if not security_monitor._enabled:  # noqa: SLF001 - internal check is intentional
        return await handler(request)

    start_ts = time.perf_counter()
    status_code = 500
    try:
        response = await handler(request)
        status_code = response.status
        return response
    except web.HTTPException as exc:
        status_code = exc.status
        raise
    except Exception:
        logger.exception("Unhandled exception while processing request")
        status_code = 500
        security_monitor.ingest_log_record("ERROR", "Unhandled exception in request handler")
        raise
    finally:
        duration = time.perf_counter() - start_ts
        try:
            await security_monitor.record_request(
                path=request.rel_url.path,
                method=request.method,
                status=status_code,
                source_ip=request.remote,
                user_agent=request.headers.get("User-Agent"),
                query=request.rel_url.query_string,
                response_time=duration,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to record request in security monitor")


async def security_status_handler(_: web.Request) -> web.Response:
    return web.json_response(security_monitor.get_status())


def setup_security(app: web.Application, *, enabled: bool = True, allowed_paths: Iterable[str] | None = None) -> None:
    """Attach middleware and status endpoint to the aiohttp app."""
    security_monitor.configure(enabled=enabled, allowed_paths=allowed_paths)
    if enabled:
        app.middlewares.append(security_middleware)
    app.router.add_get("/security_status", security_status_handler)
