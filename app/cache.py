"""Caching helpers for catalog-aware fast paths."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pickle
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Tuple, TypeVar

try:  # pragma: no cover - optional dependency
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - redis not available during tests
    Redis = None  # type: ignore[assignment]

from app.catalog.loader import catalog_version
from app.config import settings

T = TypeVar("T")

_DEFAULT_TTL = int(os.getenv("CACHE_TTL", "90"))
_NAMESPACE = "catalog-cache"


class CacheBackend:
    async def get(self, key: str) -> Any:
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl: int) -> None:
        raise NotImplementedError

    async def clear(self) -> None:
        raise NotImplementedError


@dataclass
class MemoryCache(CacheBackend):
    store: Dict[str, Tuple[float, Any]]
    lock: asyncio.Lock

    async def get(self, key: str) -> Any:
        async with self.lock:
            record = self.store.get(key)
            if record is None:
                return None
            expires, value = record
            if expires and expires < time.monotonic():
                self.store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self.lock:
            expires = time.monotonic() + ttl if ttl else 0.0
            self.store[key] = (expires, value)

    async def clear(self) -> None:
        async with self.lock:
            self.store.clear()


@dataclass
class RedisCache(CacheBackend):
    client: "Redis"

    async def get(self, key: str) -> Any:
        raw = await self.client.get(self._ns(key))
        if raw is None:
            return None
        return pickle.loads(raw)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        payload = pickle.dumps(value)
        await self.client.set(self._ns(key), payload, ex=ttl)

    async def clear(self) -> None:
        cursor = 0
        pattern = f"{_NAMESPACE}:*"
        while True:
            cursor, keys = await self.client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await self.client.delete(*keys)
            if cursor == 0:
                break

    @staticmethod
    def _ns(key: str) -> str:
        return f"{_NAMESPACE}:{key}"


def _create_backend() -> CacheBackend:
    use_redis = os.getenv("USE_REDIS", "0") == "1"
    if use_redis and Redis is not None:
        url = settings.REDIS_URL or os.getenv("REDIS_URL")
        if url:
            return RedisCache(Redis.from_url(url))
    return MemoryCache({}, asyncio.Lock())


_BACKEND = _create_backend()


def _normalize(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple, set)):
        return [_normalize(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): _normalize(value) for key, value in sorted(obj.items(), key=lambda item: str(item[0]))}
    return repr(obj)


def _make_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = _normalize({"args": args, "kwargs": kwargs})
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()
    return f"{func_name}:{catalog_version()}:{digest}"


def catalog_cached(func_name: str, ttl: int | None = None) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    expiry = ttl or _DEFAULT_TTL

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapped(*args: Any, **kwargs: Any) -> T:
            key = _make_key(func_name, args, kwargs)
            cached = await _BACKEND.get(key)
            if cached is not None:
                return cached
            result = await func(*args, **kwargs)
            await _BACKEND.set(key, result, ttl=expiry)
            return result

        return wrapped

    return decorator


async def clear_cache() -> None:
    await _BACKEND.clear()


__all__ = ["catalog_cached", "clear_cache"]
