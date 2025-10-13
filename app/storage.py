"""Storage helpers for throttling, sessions and ACL roles."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator, MutableMapping
from copy import deepcopy
from threading import Thread
from typing import Any, Awaitable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repo import events

USE_REDIS = os.getenv("USE_REDIS", "0") == "1"

if USE_REDIS:
    from app.storage_redis import (  # type: ignore
        session_get as redis_session_get,
        session_pop as redis_session_pop,
        session_set as redis_session_set,
        touch_throttle as redis_touch_throttle,
    )

    _redis_loop = asyncio.new_event_loop()

    def _redis_loop_worker() -> None:
        asyncio.set_event_loop(_redis_loop)
        _redis_loop.run_forever()

    _redis_thread = Thread(target=_redis_loop_worker, name="redis-storage", daemon=True)
    _redis_thread.start()

    def _run_async(coro: Awaitable[Any] | asyncio.Future[Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, _redis_loop).result()

else:
    _redis_loop = None


class SessionData(MutableMapping[str, Any]):
    """A mutable mapping that persists changes back to the session store."""

    __slots__ = ("_store", "_user_id", "_data", "_parent")

    def __init__(
        self,
        store: "SessionStore",
        user_id: int,
        data: Dict[str, Any],
        parent: "SessionData" | None = None,
    ) -> None:
        self._store = store
        self._user_id = user_id
        self._data = data
        self._parent = parent

    def __getitem__(self, key: str) -> Any:
        value = self._data[key]
        if isinstance(value, dict):
            return SessionData(self._store, self._user_id, value, parent=self)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(value, SessionData):
            value = value.to_dict()
        elif isinstance(value, dict):
            value = deepcopy(value)
        self._data[key] = value
        self._persist()

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._persist()

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def _persist(self) -> None:
        if self._parent is not None:
            self._parent._persist()
        else:
            self._store._save(self._user_id, self._data)

    def clear(self) -> None:  # type: ignore[override]
        self._data.clear()
        self._persist()

    def update(self, *args: Iterable[Any], **kwargs: Any) -> None:  # type: ignore[override]
        self._data.update(*args, **kwargs)
        self._persist()

    def setdefault(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        if key not in self._data:
            value = default if default is not None else {}
            if isinstance(value, SessionData):
                value = value.to_dict()
            elif isinstance(value, dict):
                value = deepcopy(value)
            self._data[key] = value
            self._persist()
        value = self._data[key]
        if isinstance(value, dict):
            return SessionData(self._store, self._user_id, value, parent=self)
        return value

    def pop(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        if key in self._data:
            value = self._data.pop(key)
            self._persist()
            if isinstance(value, dict):
                return deepcopy(value)
            return value
        return default

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self._data)


class SessionStore(MutableMapping[int, SessionData]):
    """Hybrid session store with optional Redis backend."""

    __slots__ = ("_cache", "_ttl")

    def __init__(self, ttl: int = 3600) -> None:
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._ttl = ttl

    def __getitem__(self, key: int) -> SessionData:
        data = self._load(key)
        if data is None:
            raise KeyError(key)
        return SessionData(self, key, data)

    def __setitem__(self, key: int, value: Dict[str, Any] | SessionData) -> None:
        payload = value.to_dict() if isinstance(value, SessionData) else deepcopy(value)
        self._save(key, payload)

    def __delitem__(self, key: int) -> None:
        self.pop(key)

    def __iter__(self) -> Iterator[int]:
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def _load(self, key: int) -> Dict[str, Any] | None:
        if key in self._cache:
            return self._cache[key]
        if USE_REDIS:
            data = _run_async(redis_session_get(key))
            if data is not None:
                self._cache[key] = data
                return data
            return None
        return None

    def _save(self, key: int, data: Dict[str, Any]) -> None:
        self._cache[key] = data
        if USE_REDIS:
            _run_async(redis_session_set(key, data, ttl=self._ttl))

    def _delete(self, key: int) -> Dict[str, Any] | None:
        cached = self._cache.pop(key, None)
        if USE_REDIS:
            data = _run_async(redis_session_pop(key))
            if data is not None:
                return data
            return cached
        return cached

    def get(self, key: int, default: Any = None) -> Any:  # type: ignore[override]
        data = self._load(key)
        if data is None:
            return default
        return SessionData(self, key, data)

    def setdefault(self, key: int, default: Optional[Dict[str, Any]] = None) -> SessionData:  # type: ignore[override]
        data = self._load(key)
        if data is None:
            payload = deepcopy(default) if default is not None else {}
            self._save(key, payload)
            data = self._cache[key]
        return SessionData(self, key, data)

    def pop(self, key: int, default: Any = None) -> Any:  # type: ignore[override]
        data = self._delete(key)
        if data is None:
            return default
        return deepcopy(data)


SESSIONS = SessionStore()
THROTTLES: dict[str, dict[int, float]] = defaultdict(dict)
ACCESS_ROLES: dict[int, set[str]] = defaultdict(set)


async def set_last_plan(session: AsyncSession, user_id: int, plan: Dict[str, Any]) -> None:
    try:
        await events.log(session, user_id, "plan_generated", plan)
    except Exception:  # pragma: no cover - best-effort persistence
        logging.getLogger("storage").warning("failed to log plan_generated", exc_info=True)


async def get_last_plan(session: AsyncSession, user_id: int) -> Dict[str, Any] | None:
    try:
        event = await events.last_by(session, user_id, "plan_generated")
    except Exception:  # pragma: no cover
        logging.getLogger("storage").warning("failed to load last plan", exc_info=True)
        return None
    if event:
        return event.meta
    return None


async def commit_safely(session: Any) -> None:
    """Commit the session if it exposes a commit method."""

    commit = getattr(session, "commit", None)
    if commit is None:
        return
    try:
        result = commit()
    except TypeError:
        return
    if inspect.isawaitable(result):
        await result


def touch_throttle(user_id: int, key: str, cooldown: float) -> float:
    """Return remaining cooldown for the key and update the throttle bucket."""

    if USE_REDIS:
        return float(_run_async(redis_touch_throttle(user_id, key, cooldown)))

    if user_id is None or cooldown <= 0:
        return 0.0

    now = time.monotonic()
    bucket = THROTTLES[key]
    last = bucket.get(user_id, 0.0)
    remaining = (last + cooldown) - now
    if remaining > 0:
        return remaining
    bucket[user_id] = now
    return 0.0


def session_get(user_id: int) -> Dict[str, Any]:
    result = SESSIONS.get(user_id)
    if isinstance(result, SessionData):
        return result.to_dict()
    return result or {}


def session_set(user_id: int, data: Dict[str, Any], ttl: int = 3600) -> None:
    SESSIONS._ttl = ttl
    SESSIONS[user_id] = data


def session_pop(user_id: int) -> Dict[str, Any] | None:
    result = SESSIONS.pop(user_id, None)
    if isinstance(result, SessionData):
        return result.to_dict()
    return result


def grant_role(user_id: int, role: str) -> None:
    if user_id is None or not role:
        return
    ACCESS_ROLES[user_id].add(role)


def revoke_role(user_id: int, role: str) -> None:
    if user_id is None or not role:
        return
    roles = ACCESS_ROLES.get(user_id)
    if not roles:
        return
    roles.discard(role)
    if not roles:
        ACCESS_ROLES.pop(user_id, None)


def has_role(user_id: int, role: str) -> bool:
    if user_id is None or not role:
        return False
    return role in ACCESS_ROLES.get(user_id, set())
