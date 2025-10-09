"""Helpers for working with content overrides editable by non-developers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.content import CONTENT_ROOT

OVERRIDES_ROOT = CONTENT_ROOT / "overrides"
QUIZ_OVERRIDES_ROOT = OVERRIDES_ROOT / "quizzes"


def ensure_directories() -> None:
    """Create directory structure for overrides if it does not exist."""

    QUIZ_OVERRIDES_ROOT.mkdir(parents=True, exist_ok=True)


def quiz_override_path(name: str) -> Path:
    ensure_directories()
    safe_name = name.replace("..", "_").replace("/", "_")
    return QUIZ_OVERRIDES_ROOT / f"{safe_name}.yaml"


def load_quiz_override(name: str) -> dict[str, Any]:
    """Return quiz override dictionary or an empty mapping."""

    path = quiz_override_path(name)
    if not path.exists():
        return {}
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Override for quiz {name} must be a mapping")
    return payload


def save_quiz_override(name: str, data: dict[str, Any]) -> None:
    """Persist quiz override to disk."""

    ensure_directories()
    import yaml

    path = quiz_override_path(name)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
