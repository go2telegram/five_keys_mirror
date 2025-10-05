from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging import Handler, Logger
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class JsonLineFormatter(logging.Formatter):
    """Formatter that renders log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - short override
        payload: dict[str, Any]
        if isinstance(record.msg, dict):
            payload = dict(record.msg)
            if record.args and isinstance(record.args, dict):
                payload.update(record.args)
        else:
            payload = {"message": record.getMessage()}

        payload.setdefault("level", record.levelname.lower())
        payload.setdefault("ts", datetime.now(timezone.utc).isoformat())

        if record.exc_info:
            payload.setdefault("error", True)
            payload["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)


def _configure_handler(handler: Handler, level: int) -> None:
    handler.setLevel(level)
    handler.setFormatter(JsonLineFormatter())


def setup_logging(debug: bool, log_path: str | None) -> Logger:
    """Configure telemetry logging."""

    logger = logging.getLogger("telemetry")
    level = logging.DEBUG if debug else logging.INFO

    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    _configure_handler(stream_handler, level)
    logger.addHandler(stream_handler)

    if log_path:
        path = Path(log_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            path,
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        _configure_handler(file_handler, level)
        logger.addHandler(file_handler)

    return logger


def serialize_event(event: Any) -> Any:
    """Attempt to convert aiogram event to JSON-serialisable structure."""

    if event is None:
        return None

    model_dump = getattr(event, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json", exclude_none=True)
        except Exception:  # pragma: no cover - best effort serialisation
            pass

    return repr(event)


class TelemetryMiddleware(BaseMiddleware):
    """Middleware that records per-update telemetry."""

    def __init__(self, *, logger: Logger, debug: bool = False, slow_ms: int = 1_000) -> None:
        self.logger = logger
        self.debug = debug
        self.slow_ms = slow_ms

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        update_type = self._detect_update_type(event, data)
        user_obj = data.get("event_from_user") or data.get("from_user")
        chat_obj = data.get("event_chat") or data.get("chat") or getattr(event, "chat", None)
        user_id = getattr(user_obj, "id", None)
        chat_id = getattr(chat_obj, "id", None)

        try:
            result = await handler(event, data)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.logger.error(
                {
                    "kind": "update_error",
                    "update_type": update_type,
                    "ms": duration_ms,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "error": True,
                },
                exc_info=True,
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)

        entry = {"kind": "u", "t": update_type, "ms": duration_ms}
        if user_id is not None:
            entry["uid"] = user_id
        if chat_id is not None:
            entry["cid"] = chat_id
        self.logger.info(entry)

        if self.debug or duration_ms >= self.slow_ms:
            audit_entry = {
                "kind": "update_audit",
                "update_type": update_type,
                "ms": duration_ms,
                "user_id": user_id,
                "chat_id": chat_id,
                "raw": serialize_event(event),
            }
            self.logger.info(audit_entry)

        return result

    @staticmethod
    def _detect_update_type(event: TelegramObject, data: Dict[str, Any]) -> str:
        update = data.get("update")
        if update is not None:
            event_type = getattr(update, "event_type", None)
            if event_type:
                return str(event_type)

        event_type = getattr(event, "event_type", None)
        if event_type:
            return str(event_type)

        return event.__class__.__name__
