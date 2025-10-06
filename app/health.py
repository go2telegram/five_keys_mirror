from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Dict

from aiohttp import web
from sqlalchemy import text

from app.db.session import session_scope


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecoverySnapshot:
    count: int
    last_reason: str | None
    last_at: str | None
    pending: bool
    pending_reason: str | None


class RecoveryState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._count = 0
        self._last_reason: str | None = None
        self._last_at: dt.datetime | None = None
        self._pending_reason: str | None = None

    async def request(self, reason: str) -> None:
        async with self._lock:
            if self._pending_reason is None:
                logger.warning("Scheduling recovery: %s", reason)
            else:
                logger.warning(
                    "Recovery already pending (%s); new reason: %s",
                    self._pending_reason,
                    reason,
                )
            self._pending_reason = reason

    async def mark_recovered(self) -> None:
        async with self._lock:
            if self._pending_reason is None:
                return

            self._count += 1
            self._last_reason = self._pending_reason
            self._last_at = dt.datetime.now(dt.timezone.utc)
            self._pending_reason = None
            logger.info("Recovery complete. Total recoveries: %s", self._count)

    async def snapshot(self) -> RecoverySnapshot:
        async with self._lock:
            return RecoverySnapshot(
                count=self._count,
                last_reason=self._last_reason,
                last_at=self._last_at.isoformat() if self._last_at else None,
                pending=self._pending_reason is not None,
                pending_reason=self._pending_reason,
            )


recovery_state = RecoveryState()


async def ping_handler(_: web.Request) -> web.Response:
    """Simple liveness probe that also exercises the database connection."""

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - propagate error in response
        snapshot = await recovery_state.snapshot()
        payload: Dict[str, Any] = {
            "status": "error",
            "detail": str(exc),
            "recovery": snapshot.__dict__,
        }
        return web.json_response(payload, status=503)

    snapshot = await recovery_state.snapshot()
    payload: Dict[str, Any] = {
        "status": "ok",
        "recovery": snapshot.__dict__,
    }
    return web.json_response(payload)


def setup_healthcheck(app_web: web.Application) -> None:
    app_web.router.add_get("/ping", ping_handler)
