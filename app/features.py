"""Простые feature flags для бота."""
from __future__ import annotations

from typing import Dict

_FEATURE_FLAGS: Dict[str, bool] = {
    "auto_notify": True,
}


def is_feature_enabled(name: str) -> bool:
    return _FEATURE_FLAGS.get(name, True)


def disable_feature(name: str) -> bool:
    previous = _FEATURE_FLAGS.get(name, True)
    _FEATURE_FLAGS[name] = False
    return previous


def enable_feature(name: str) -> None:
    _FEATURE_FLAGS[name] = True

