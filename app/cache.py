"""Caching helpers for catalog-aware fast paths using aiocache."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Awaitable, Callable, TypeVar

try:  # pragma: no cover - prefer real aiocache when available
    from aiocache import Cache
    from aiocache.serializers import PickleSerializer
except Exception:  # pragma: no cover - offline test fallback
    from app._compat.aiocache_stub import Cache, PickleSerializer

from app.catalog.loader import CATALOG_SHA, catalog_version
from app.config import settings

T = TypeVar("T")

_DEFAULT_TTL = int(os.getenv("CACHE_TTL", "90"))
_NAMESPACE = "catalog-cache"


def _create_cache() -> Cache:
    """Return a configured aiocache backend with Redis fallback."""

    use_redis = os.getenv("USE_REDIS", "0") == "1"
    if use_redis:
        url = settings.REDIS_URL or os.getenv("REDIS_URL")
        if url:
            try:
                return Cache.from_url(
                    url,
                    namespace=_NAMESPACE,
                    serializer=PickleSerializer(),
                )
            except Exception:  # pragma: no cover - fallback to in-memory cache
                logging.getLogger("cache").exception("redis cache init failed")

    return Cache(
        Cache.MEMORY,
        namespace=_NAMESPACE,
        serializer=PickleSerializer(),
    )


_CACHE = _create_cache()


def _normalize(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple, set)):
        return [_normalize(item) for item in obj]
    if isinstance(obj, dict):
        return {
            str(key): _normalize(value)
            for key, value in sorted(obj.items(), key=lambda item: str(item[0]))
        }
    return repr(obj)


def _make_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = _normalize({"args": args, "kwargs": kwargs})
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()
    version = catalog_version()
    return f"{CATALOG_SHA}:{version}:{func_name}:{digest}"


def catalog_cached(
    func_name: str,
    ttl: int | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorate an async callable with catalog-aware caching."""

    expiry = ttl or _DEFAULT_TTL

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapped(*args: Any, **kwargs: Any) -> T:
            key = _make_key(func_name, args, kwargs)
            cached = await _CACHE.get(key)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            if result is not None:
                await _CACHE.set(key, result, ttl=expiry)
            return result

        return wrapped

    return decorator


async def clear_cache() -> None:
    await _CACHE.clear()


__all__ = ["catalog_cached", "clear_cache"]
