"""In-memory idempotency helpers for long-running operations."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable, Tuple, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class _Entry:
    timestamp: float
    future: asyncio.Future[Any]


class IdempotencyToken:
    """A token representing access to an idempotent operation."""

    def __init__(
        self,
        manager: "InMemoryIdempotency",
        key: str,
        future: asyncio.Future[Any],
        owner: bool,
    ) -> None:
        self._manager = manager
        self._key = key
        self._future = future
        self.is_owner = owner
        self._released = False

    async def wait(self) -> Any:
        """Wait for the guarded operation to complete and return its result."""

        return await self._future

    async def complete(self, result: Any = None) -> Any:
        """Mark the guarded operation as completed successfully."""

        if not self.is_owner:
            return result
        if not self._future.done():
            self._future.set_result(result)
        self._released = True
        await self._manager._finalize(self._key, self._future, success=True)
        return result

    async def fail(self, exc: BaseException) -> None:
        """Mark the guarded operation as failed."""

        if not self.is_owner:
            return
        if not self._future.done():
            self._future.set_exception(exc)
        self._released = True
        await self._manager._finalize(self._key, self._future, success=False)

    async def __aenter__(self) -> "IdempotencyToken":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if not self.is_owner:
            return False
        if exc is not None:
            await self.fail(exc)
            return False
        if not self._released:
            await self.complete(None)
        return False


class InMemoryIdempotency:
    """A simple in-memory idempotency key registry."""

    def __init__(self, *, ttl: float = 120.0, maxsize: int = 1024) -> None:
        self._ttl = max(0.0, float(ttl))
        self._maxsize = max(1, int(maxsize))
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def acquire(self, key: str | None) -> IdempotencyToken:
        """Acquire a token for the supplied key."""

        if not key or self._ttl <= 0:
            loop = asyncio.get_running_loop()
            return IdempotencyToken(
                self,
                key or "",
                loop.create_future(),
                owner=True,
            )

        loop = asyncio.get_running_loop()
        async with self._lock:
            now = monotonic()
            self._purge(now)
            entry = self._entries.get(key)
            if entry is not None:
                entry.timestamp = now
                self._entries.move_to_end(key)
                return IdempotencyToken(self, key, entry.future, owner=False)

            future: asyncio.Future[Any] = loop.create_future()
            self._entries[key] = _Entry(timestamp=now, future=future)
            self._shrink()
            return IdempotencyToken(self, key, future, owner=True)

    async def run(
        self, key: str | None, func: Callable[[], Awaitable[T]]
    ) -> Tuple[T, bool]:
        """Execute *func* once per key and return (result, is_owner)."""

        token = await self.acquire(key)
        if not token.is_owner:
            result = await token.wait()
            return result, False

        async with token:
            result = await func()
            await token.complete(result)
            return result, True

    async def _finalize(
        self, key: str, future: asyncio.Future[Any], *, success: bool
    ) -> None:
        if not key:
            return
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.future is not future:
                return
            if not success:
                self._entries.pop(key, None)
                return
            entry.timestamp = monotonic()
            self._entries.move_to_end(key)
            self._shrink()

    def _purge(self, now: float) -> None:
        if not self._entries:
            return
        expired: list[str] = []
        for key, entry in self._entries.items():
            if entry.future.done():
                if now - entry.timestamp > self._ttl:
                    expired.append(key)
            elif now - entry.timestamp > self._ttl * 4:
                expired.append(key)
        for key in expired:
            self._entries.pop(key, None)

    def _shrink(self) -> None:
        if len(self._entries) <= self._maxsize:
            return
        keys = list(self._entries.keys())
        for key in keys:
            entry = self._entries.get(key)
            if entry is None:
                continue
            if entry.future.done() or len(self._entries) > self._maxsize * 2:
                self._entries.pop(key, None)
            if len(self._entries) <= self._maxsize:
                break


def make_idempotency_key(*parts: object | None) -> str | None:
    """Create a compact key from arbitrary parts."""

    tokens = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            tokens.append(text)
    if not tokens:
        return None
    raw = ":".join(tokens)
    if len(raw) <= 96:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{tokens[0]}:{digest}"


idempotency_registry = InMemoryIdempotency()


__all__ = ["IdempotencyToken", "InMemoryIdempotency", "idempotency_registry", "make_idempotency_key"]
