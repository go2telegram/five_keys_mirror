from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, Mapping

from app.config import settings


class FeatureFlagManager:
    """Простая in-memory обёртка над JSON c фич-флагами."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path or settings.FEATURE_FLAGS_PATH)
        self._lock = RLock()
        self._flags: Dict[str, Dict[str, Any]] = {}
        self.reload()

    # -- API --
    def reload(self) -> None:
        data = self._read_file()
        with self._lock:
            self._flags = data

    def all_flags(self) -> Mapping[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._flags)

    def get_flag(self, key: str) -> Dict[str, Any] | None:
        with self._lock:
            flag = self._flags.get(key)
            return dict(flag) if flag else None

    def is_enabled(self, key: str, user: Any | None = None) -> bool:
        flag = self.get_flag(key)
        if not flag:
            return False
        if not flag.get("enabled", False):
            return False
        rollout = flag.get("rollout")
        if rollout is None:
            return True
        user_id = _user_id(user)
        if user_id is None:
            return False
        bucket = _user_bucket(user_id, key)
        try:
            rollout_value = int(rollout)
        except (TypeError, ValueError):
            return False
        return bucket < max(0, min(rollout_value, 100))

    def variant(self, key: str, user: Any | None = None) -> str:
        flag = self.get_flag(key)
        default_variant = flag.get("default_variant", "control") if flag else "control"
        if not flag or not flag.get("enabled", False):
            return default_variant
        user_id = _user_id(user)
        if user_id is None:
            return default_variant
        bucket = _user_bucket(user_id, key)
        variants = flag.get("variants")
        if isinstance(variants, Mapping):
            total = 0
            for name, portion in _iter_variants(variants):
                total += portion
                if bucket < total:
                    return name
            return default_variant
        rollout = flag.get("rollout")
        if rollout is None:
            return default_variant
        try:
            rollout_value = int(rollout)
        except (TypeError, ValueError):
            return default_variant
        rollout_value = max(0, min(rollout_value, 100))
        if bucket < rollout_value:
            return str(flag.get("variant_true", "B"))
        return str(flag.get("variant_false", default_variant))

    # -- internals --
    def _read_file(self) -> Dict[str, Dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text("utf-8")
            data = json.loads(raw)
        except Exception:
            return {}
        flags: Dict[str, Dict[str, Any]] = {}
        if isinstance(data, Mapping):
            for key, value in data.items():
                if isinstance(key, str) and isinstance(value, Mapping):
                    flags[key] = dict(value)
        return flags


def _user_id(user: Any | None) -> int | None:
    if user is None:
        return None
    if isinstance(user, int):
        return user
    if hasattr(user, "id"):
        try:
            return int(getattr(user, "id"))
        except (TypeError, ValueError):
            return None
    if hasattr(user, "from_user") and getattr(user, "from_user") is not None:
        return _user_id(getattr(user, "from_user"))
    try:
        return int(user)
    except (TypeError, ValueError):
        return None


def _user_bucket(user_id: int, key: str, buckets: int = 100) -> int:
    payload = f"{key}:{user_id}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:8], 16) % buckets


def _iter_variants(variants: Mapping[str, Any]) -> Iterable[tuple[str, int]]:
    for name, portion in variants.items():
        try:
            yield str(name), int(portion)
        except (TypeError, ValueError):
            continue


flags = FeatureFlagManager()
