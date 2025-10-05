from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path
from typing import Iterable

MASK_PLACEHOLDER = "<MASKED>"

# Patterns that try to catch secrets written as key=value or JSON pairs.
KEY_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(token|api[_-]?key|secret|password|pass|key)\s*[:=]\s*([^\s'\";]+)"),
    re.compile(r"(?i)\"(token|api[_-]?key|secret|password|pass|key)\"\s*:\s*\"([^\"\\]+)\""),
)

# Token-like strings — long, high-entropy identifiers (e.g. Telegram tokens, API keys).
TOKEN_LIKE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{24,})(?![A-Za-z0-9_-])")


def _iter_secret_values() -> Iterable[str]:
    """Collect potential secret values from environment variables."""

    for key, value in os.environ.items():
        if not value:
            continue
        key_upper = key.upper()
        if any(marker in key_upper for marker in ("TOKEN", "SECRET", "KEY", "PASS", "PWD", "DSN")):
            yield value

    try:
        from app.config import settings  # noqa: WPS433 (late import to avoid cycles)
    except Exception:  # pragma: no cover - settings import shouldn't fail in runtime
        return

    for key, value in settings.model_dump().items():
        if not isinstance(value, str) or not value:
            continue
        key_upper = key.upper()
        if any(marker in key_upper for marker in ("TOKEN", "SECRET", "KEY", "PASS", "PWD", "DSN")):
            yield value


def _mask_known_values(text: str) -> str:
    for value in _iter_secret_values():
        if len(value) < 4:
            continue
        # Use a placeholder that keeps minimal information about length.
        placeholder = f"{MASK_PLACEHOLDER}[len={len(value)}]"
        text = text.replace(value, placeholder)
    return text


def _mask_key_value_patterns(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        return match.group(0).replace(match.group(2), MASK_PLACEHOLDER)

    for pattern in KEY_VALUE_PATTERNS:
        text = pattern.sub(_sub, text)
    return text


def _mask_token_like(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if len(token) < 24:
            return token
        return MASK_PLACEHOLDER

    return TOKEN_LIKE_PATTERN.sub(_sub, text)


def mask_secrets(text: str) -> str:
    """Mask likely secrets inside the provided text."""

    masked = _mask_known_values(text)
    masked = _mask_key_value_patterns(masked)
    masked = _mask_token_like(masked)
    return masked


def tail_logs(path: str | Path, lines: int = 60, max_length: int = 3500) -> str:
    """Return the last ``lines`` lines from the log file, masking secrets."""

    log_path = Path(path)
    if not log_path.exists():
        return "Лог-файл не найден."

    buffer: deque[str] = deque(maxlen=max(1, lines))
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                buffer.append(raw_line.rstrip("\n"))
    except OSError as exc:
        return f"Не удалось прочитать лог: {exc}"  # pragma: no cover

    text = "\n".join(buffer)
    text = mask_secrets(text)

    if len(text) > max_length:
        text = text[: max_length - 3] + "..."

    return text or "Лог пуст."
