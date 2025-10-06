"""Product event tracking helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from app.metrics import product as product_metrics

_LOGGER = logging.getLogger("product_events")
if not _LOGGER.handlers:
    _LOGGER.setLevel(logging.INFO)
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs_dir / "events.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v) for v in value]
    return str(value)


def _sync_track(event: str, user_id: int | None, props: Dict[str, Any]) -> None:
    ts = _now()
    product_metrics.record_event(event, user_id, ts, props)
    entry = {
        "ts": ts.isoformat(),
        "event": event,
        "user_id": user_id,
        "props": {k: _sanitize(v) for k, v in props.items()},
    }
    _LOGGER.info(json.dumps(entry, ensure_ascii=False, sort_keys=True))


async def track(event: str, user_id: int | None, **props: Any) -> None:
    """Track a product event."""

    await asyncio.to_thread(_sync_track, event, user_id, props)
