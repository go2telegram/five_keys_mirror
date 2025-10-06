"""Utility helpers for resilient connections to external services."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings

try:  # pragma: no cover - optional dependency guards
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover - noqa: BLE001
    asyncpg = None  # type: ignore

try:  # pragma: no cover - optional dependency guards
    from redis.asyncio import Redis as AsyncRedis  # type: ignore
    from redis.asyncio import from_url as redis_from_url  # type: ignore
except Exception:  # pragma: no cover - noqa: BLE001
    AsyncRedis = None  # type: ignore
    redis_from_url = None  # type: ignore


logger = logging.getLogger(__name__)

_BACKOFF_STEPS = (1.0, 2.0, 5.0)
_MAX_RETRY_WINDOW = 300.0  # seconds (5 минут)

_db_pool: Optional["asyncpg.Pool"] = None
_cache_backend: "BaseCache | None" = None


@dataclass(slots=True)
class BaseCache:
    """Abstract interface for cache backends."""

    async def get(self, key: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def delete(self, *keys: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - interface
        return None

    async def health_check(self) -> None:  # pragma: no cover - interface
        return None


class RedisCache(BaseCache):
    def __init__(self, client: AsyncRedis) -> None:  # type: ignore[name-defined]
        self._client = client

    async def get(self, key: str) -> Any:
        return await self._client.get(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        await self._client.set(name=key, value=value, ex=ex)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def close(self) -> None:
        await self._client.close()

    async def health_check(self) -> None:
        await self._client.ping()


class InMemoryCache(BaseCache):
    """Fallback cache that keeps data in-process."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._expirations: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _purge(self) -> None:
        if not self._expirations:
            return
        now = time.monotonic()
        expired = [key for key, ts in self._expirations.items() if ts <= now]
        for key in expired:
            self._store.pop(key, None)
            self._expirations.pop(key, None)

    async def get(self, key: str) -> Any:
        async with self._lock:
            self._purge()
            return self._store.get(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        async with self._lock:
            self._store[key] = value
            if ex is None:
                self._expirations.pop(key, None)
            else:
                self._expirations[key] = time.monotonic() + ex

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        async with self._lock:
            for key in keys:
                self._store.pop(key, None)
                self._expirations.pop(key, None)


def _backoff_delay(attempt: int) -> float:
    idx = min(max(attempt - 1, 0), len(_BACKOFF_STEPS) - 1)
    return _BACKOFF_STEPS[idx]


async def init_db_safe(force: bool = False) -> Optional["asyncpg.Pool"]:
    """Initialise a PostgreSQL connection pool with retries and logging."""
    global _db_pool

    if asyncpg is None:  # type: ignore[truthy-function]
        logger.warning("asyncpg is not available; PostgreSQL disabled", extra={"phase": "skip", "service": "postgres"})
        _db_pool = None
        return None

    if _db_pool is not None and not force:
        return _db_pool

    if not settings.DATABASE_URL:
        logger.info("DATABASE_URL is not configured; running without PostgreSQL", extra={"phase": "skip", "service": "postgres"})
        _db_pool = None
        return None

    deadline = time.monotonic() + _MAX_RETRY_WINDOW
    attempt = 0

    while True:
        attempt += 1
        try:
            logger.info(
                "Connecting to PostgreSQL (attempt %s)",
                attempt,
                extra={"phase": "connect", "service": "postgres"},
            )
            pool = await asyncpg.create_pool(settings.DATABASE_URL, timeout=10)  # type: ignore[arg-type]
            await pool.fetchval("SELECT 1")
            _db_pool = pool
            logger.info(
                "PostgreSQL connection established",
                extra={"phase": "ready", "service": "postgres"},
            )
            return pool
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            logger.warning(
                "PostgreSQL connection failed: %s",
                exc,
                extra={"phase": "retry", "service": "postgres", "attempt": attempt},
            )
            if now >= deadline:
                logger.error(
                    "PostgreSQL connection retries exhausted; continuing without DB",
                    extra={"phase": "fail", "service": "postgres"},
                )
                _db_pool = None
                return None
            delay = min(_backoff_delay(attempt + 1), max(deadline - now, 0))
            if delay <= 0:
                continue
            logger.info(
                "Retrying PostgreSQL in %.1fs",
                delay,
                extra={"phase": "sleep", "service": "postgres", "attempt": attempt},
            )
            await asyncio.sleep(delay)


def get_db_pool() -> Optional["asyncpg.Pool"]:
    """Return the current PostgreSQL pool (may be ``None`` when unavailable)."""
    return _db_pool


async def close_db_pool() -> None:
    global _db_pool
    pool = _db_pool
    if pool is not None:
        await pool.close()
    _db_pool = None


async def init_cache_safe(force: bool = False) -> BaseCache:
    """Initialise Redis cache with retries and automatic in-memory fallback."""
    global _cache_backend

    if _cache_backend is not None and not force:
        return _cache_backend

    if AsyncRedis is None or redis_from_url is None:
        logger.warning(
            "redis library is not available; using in-memory cache",
            extra={"phase": "skip", "service": "redis"},
        )
        _cache_backend = InMemoryCache()
        return _cache_backend

    if not settings.REDIS_URL:
        logger.info(
            "REDIS_URL is not configured; using in-memory cache",
            extra={"phase": "skip", "service": "redis"},
        )
        _cache_backend = InMemoryCache()
        return _cache_backend

    deadline = time.monotonic() + _MAX_RETRY_WINDOW
    attempt = 0

    while True:
        attempt += 1
        try:
            logger.info(
                "Connecting to Redis (attempt %s)",
                attempt,
                extra={"phase": "connect", "service": "redis"},
            )
            client = redis_from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)  # type: ignore[call-arg]
            await client.ping()
            _cache_backend = RedisCache(client)
            logger.info(
                "Redis connection established",
                extra={"phase": "ready", "service": "redis"},
            )
            return _cache_backend
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            logger.warning(
                "Redis connection failed: %s",
                exc,
                extra={"phase": "retry", "service": "redis", "attempt": attempt},
            )
            if now >= deadline:
                logger.error(
                    "Redis connection retries exhausted; switching to in-memory cache",
                    extra={"phase": "fail", "service": "redis"},
                )
                _cache_backend = InMemoryCache()
                return _cache_backend
            delay = min(_backoff_delay(attempt + 1), max(deadline - now, 0))
            if delay <= 0:
                continue
            logger.info(
                "Retrying Redis in %.1fs",
                delay,
                extra={"phase": "sleep", "service": "redis", "attempt": attempt},
            )
            await asyncio.sleep(delay)


def get_cache() -> BaseCache:
    """Return the configured cache backend (initialises fallback if required)."""
    global _cache_backend
    if _cache_backend is None:
        # lazy initialisation for synchronous contexts
        _cache_backend = InMemoryCache()
    return _cache_backend


async def reset_cache_backend() -> None:
    """Close and drop the active cache backend (used in tests)."""
    global _cache_backend
    backend = _cache_backend
    if backend is not None:
        try:
            await backend.close()
        except Exception:  # noqa: BLE001
            logger.debug("Ignoring cache close error", exc_info=True)
    _cache_backend = None
