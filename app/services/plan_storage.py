"""Utilities to persist AI plan revisions."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Mapping

from app.config import settings

_PLAN_DIR = Path(getattr(settings, "PLAN_ARCHIVE_DIR", "var/plans") or "var/plans")


def plan_archive_dir() -> Path:
    """Return the directory used to store plan history."""

    return _PLAN_DIR


def archive_plan(user_id: int, plan_json: Mapping[str, Any]) -> Path:
    """Write a plan revision to disk and return the file path."""

    directory = plan_archive_dir()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = directory / f"{user_id}_{timestamp}.json"
    payload = dict(plan_json)
    payload.setdefault("user_id", user_id)
    payload.setdefault("generated_at", dt.datetime.now(dt.timezone.utc).isoformat())
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
