"""Minimal subset of aiocache API for offline test environments."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class PickleSerializer:
    """Drop-in replacement for aiocache PickleSerializer."""

    @staticmethod
    def dumps(value: Any) -> bytes:
        import pickle

        return pickle.dumps(value)

    @staticmethod
    def loads(value: bytes) -> Any:
        import pickle

        return pickle.loads(value)


class Cache:
    MEMORY = "memory"

    def __init__(
        self,
        _backend: str,
        *,
        namespace: str | None = None,
        serializer: PickleSerializer | None = None,
    ) -> None:
        self._namespace = namespace or ""
        self._serializer = serializer or PickleSerializer()
        self._store: dict[str, tuple[float | None, bytes]] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_url(cls, _url: str, **kwargs: Any) -> "Cache":
        # Fallback to in-memory cache when Redis is unavailable offline.
        return cls(cls.MEMORY, **kwargs)

    def _ns(self, key: str) -> str:
        return f"{self._namespace}:{key}" if self._namespace else key

    async def get(self, key: str) -> Any:
        namespaced = self._ns(key)
        async with self._lock:
            record = self._store.get(namespaced)
            if record is None:
                return None
            expires, payload = record
            if expires is not None and expires <= time.monotonic():
                self._store.pop(namespaced, None)
                return None
            return self._serializer.loads(payload)

    async def set(self, key: str, value: Any, ttl: int | float | None = None) -> None:
        namespaced = self._ns(key)
        expiry = time.monotonic() + float(ttl) if ttl else None
        payload = self._serializer.dumps(value)
        async with self._lock:
            self._store[namespaced] = (expiry, payload)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
