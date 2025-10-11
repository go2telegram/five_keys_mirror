"""Helpers for accessing build metadata."""

from __future__ import annotations

from typing import TypedDict


class BuildInfo(TypedDict, total=False):
    """Structured representation of build metadata."""

    version: str
    commit: str
    timestamp: str


_UNKNOWN = "unknown"


def _sanitize(value: object) -> str:
    """Return a safe string for build metadata fields."""

    if isinstance(value, str) and value:
        return value
    return _UNKNOWN


def get_build_info() -> BuildInfo:
    """Return build information with safe fallbacks.

    The function tolerates missing or partially-populated ``app.build_info``
    modules to make local development more convenient.
    """

    try:  # pragma: no cover - defensive import wrapper
        from app import build_info as build_module  # type: ignore
    except Exception:
        return {"version": _UNKNOWN, "commit": _UNKNOWN, "timestamp": _UNKNOWN}

    # The build module may expose a dictionary (preferred) or legacy globals.
    build_dict = getattr(build_module, "BUILD", None)
    if isinstance(build_dict, dict):
        version = _sanitize(build_dict.get("version"))
        commit = _sanitize(build_dict.get("commit"))
        timestamp = _sanitize(build_dict.get("timestamp"))
    else:
        version = _sanitize(getattr(build_module, "VERSION", None))
        if version == _UNKNOWN:
            # Fall back to branch name for older builds
            version = _sanitize(getattr(build_module, "GIT_BRANCH", None))
        commit = _sanitize(getattr(build_module, "GIT_COMMIT", None))
        timestamp = _sanitize(getattr(build_module, "BUILD_TIME", None))

    return {"version": version, "commit": commit, "timestamp": timestamp}
