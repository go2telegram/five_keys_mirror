"""Runtime feature flag management with optional canary rollout support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Mapping

from app.config import Settings, settings
from app.storage import USE_REDIS

logger = logging.getLogger(__name__)


_ALL_FLAGS = {
    "FF_NEW_ONBOARDING",
    "FF_QUIZ_GUARD",
    "FF_NAV_FOOTER",
    "FF_MEDIA_PROXY",
}
_CANARY_FLAGS = {"FF_NEW_ONBOARDING", "FF_NAV_FOOTER"}


class FeatureFlagManager:
    """Manage feature flags backed by settings with optional persistence."""

    def __init__(
        self,
        settings_obj: Settings | None = None,
        *,
        use_redis: bool | None = None,
    ) -> None:
        self._settings = settings_obj or settings
        self._use_redis = USE_REDIS if use_redis is None else use_redis
        self._defaults = self._collect_defaults()
        self._flags = dict(self._defaults)
        self._overrides: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        """Load overrides from persistent storage."""

        async with self._lock:
            overrides = await self._load_overrides()
            self._overrides = overrides
            self._rebuild_flags()
            logger.info("feature flags initialized overrides=%s", overrides)

    def is_enabled(self, flag: str, *, user_id: int | None = None) -> bool:
        """Return True if a flag is enabled for the optional user."""

        enabled = self._flags.get(flag)
        if enabled is None:
            return False
        if enabled:
            return True
        if user_id is None:
            return False
        if flag not in _CANARY_FLAGS:
            return False
        return self._is_canary_user(user_id)

    def snapshot(self) -> dict[str, bool]:
        """Return a copy of the effective flag values (without canary)."""

        return dict(self._flags)

    def defaults(self) -> Mapping[str, bool]:
        """Expose default values for unit tests and status reporting."""

        return dict(self._defaults)

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._defaults))

    def canary_flags(self) -> tuple[str, ...]:
        return tuple(sorted(_CANARY_FLAGS))

    async def set_flag(self, flag: str, enabled: bool) -> None:
        """Persistently enable or disable a feature flag."""

        if flag not in self._defaults:
            raise KeyError(f"Unknown feature flag: {flag}")

        normalized = bool(enabled)
        default_value = self._defaults[flag]

        async with self._lock:
            if normalized == default_value:
                self._overrides.pop(flag, None)
                await self._persist_delete(flag)
            else:
                self._overrides[flag] = normalized
                await self._persist_set(flag, normalized)
            self._rebuild_flags()
            logger.info(
                "feature flag updated flag=%s enabled=%s overrides=%s",
                flag,
                normalized,
                self._overrides,
            )

    async def refresh(self) -> None:
        """Reload the overrides from the persistent store."""

        await self.initialize()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------
    def environment(self) -> str:
        value = getattr(self._settings, "ENVIRONMENT", "") or "local"
        return str(value)

    def canary_percent(self) -> int:
        percent = getattr(self._settings, "CANARY_PERCENT", 0)
        try:
            percent_int = int(percent)
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, percent_int))

    def is_canary_user(self, user_id: int) -> bool:
        return self._is_canary_user(user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _collect_defaults(self) -> dict[str, bool]:
        defaults: dict[str, bool] = {}
        for flag in _ALL_FLAGS:
            defaults[flag] = bool(getattr(self._settings, flag, False))
        return defaults

    async def _load_overrides(self) -> dict[str, bool]:
        if self._use_redis:
            try:
                from app import storage_redis

                raw = await storage_redis.feature_flags_all()
                return {flag: bool(value) for flag, value in raw.items()}
            except Exception:  # pragma: no cover - redis unavailable at runtime
                logger.exception("Failed to load feature flags from Redis; falling back to file")
        return self._load_overrides_from_file()

    def _load_overrides_from_file(self) -> dict[str, bool]:
        path = Path(getattr(self._settings, "FEATURE_FLAGS_FILE", "var/feature_flags.json"))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.warning("Invalid feature flag override file: %s", path)
            return {}
        if not isinstance(payload, Mapping):
            return {}
        overrides: dict[str, bool] = {}
        for key, value in payload.items():
            if key in self._defaults:
                overrides[str(key)] = bool(value)
        return overrides

    def _rebuild_flags(self) -> None:
        combined = dict(self._defaults)
        combined.update(self._overrides)
        self._flags = combined

    async def _persist_set(self, flag: str, enabled: bool) -> None:
        if self._use_redis:
            try:
                from app import storage_redis

                await storage_redis.feature_flags_set(flag, enabled)
                return
            except Exception:  # pragma: no cover - redis runtime issues
                logger.exception("Failed to persist feature flag to Redis; writing file fallback")
        self._write_file()

    async def _persist_delete(self, flag: str) -> None:
        if self._use_redis:
            try:
                from app import storage_redis

                await storage_redis.feature_flags_delete(flag)
                return
            except Exception:  # pragma: no cover - redis runtime issues
                logger.exception("Failed to delete feature flag from Redis; writing file fallback")
        self._write_file()

    def _write_file(self) -> None:
        path = Path(getattr(self._settings, "FEATURE_FLAGS_FILE", "var/feature_flags.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        filtered = {key: value for key, value in self._overrides.items() if key in self._defaults}
        path.write_text(json.dumps(filtered, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    def _is_canary_user(self, user_id: int) -> bool:
        if not user_id:
            return False
        percent = self.canary_percent()
        if percent <= 0:
            return False
        digest = hashlib.sha1(f"canary:{user_id}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % 100
        return bucket < percent


feature_flags = FeatureFlagManager()


__all__ = ["FeatureFlagManager", "feature_flags"]

