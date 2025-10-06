from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Iterable, List

from app.config import settings


def _mask_secret(value: str) -> str:
    clean = value.strip()
    if not clean:
        return "***"
    if len(clean) <= 4:
        return "*" * len(clean)
    return f"{clean[:2]}…{clean[-2:]}"


def _collect_sensitive_values() -> List[str]:
    candidates: Iterable[str | None] = (
        getattr(settings, "BOT_TOKEN", None),
        getattr(settings, "CALLBACK_SECRET", None),
        getattr(settings, "OPENAI_API_KEY", None),
        getattr(settings, "TRIBUTE_API_KEY", None),
    )
    return [value for value in candidates if isinstance(value, str) and value]


_REDACTION_MAP = {secret: _mask_secret(secret) for secret in _collect_sensitive_values()}
_LOG_HISTORY: Deque[str] = deque(maxlen=500)
_CONFIGURED = False


def register_secret(value: str | None) -> None:
    if not value:
        return
    if value not in _REDACTION_MAP:
        _REDACTION_MAP[value] = _mask_secret(value)


def redact_text(text: str) -> str:
    redacted = text
    for secret, masked in _REDACTION_MAP.items():
        redacted = redacted.replace(secret, masked)
    return redacted


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact_text(formatted)


class PanelLogHandler(logging.Handler):
    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - logging handler API
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - logging framework safeguards
            return
        _LOG_HISTORY.append(message)


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = RedactingFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    if not root.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    else:
        for existing in root.handlers:
            existing.setFormatter(formatter)

    buffer_handler = PanelLogHandler(formatter)
    buffer_handler.setLevel(level)
    root.addHandler(buffer_handler)

    root.setLevel(level)

    _CONFIGURED = True


def get_panel_logs(limit: int | None = None) -> list[str]:
    if limit is None:
        return list(_LOG_HISTORY)
    if limit <= 0:
        return []
    return list(_LOG_HISTORY)[-limit:]
