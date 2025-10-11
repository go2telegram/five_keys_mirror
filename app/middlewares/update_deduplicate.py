"""Middleware that de-duplicates incoming Telegram updates."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict
from time import monotonic
from typing import Any, Awaitable, Callable, Dict, Tuple

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

logger = logging.getLogger("updates.deduplicate")


class UpdateDeduplicateMiddleware(BaseMiddleware):
    """Drop duplicated updates within a short time window."""

    def __init__(self, *, ttl: float = 10.0, maxsize: int = 2048) -> None:
        self._ttl = max(0.0, float(ttl))
        self._maxsize = max(1, int(maxsize))
        self._cache: OrderedDict[Tuple[int | None, int | None, str | None], float] = OrderedDict()
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        key = self._make_key(event)
        if key is None or self._ttl <= 0:
            return await handler(event, data)

        now = monotonic()
        async with self._lock:
            self._purge(now)
            last_seen = self._cache.get(key)
            duplicate = last_seen is not None and now - last_seen < self._ttl
            self._cache[key] = now
            self._cache.move_to_end(key)
            self._shrink()

        if duplicate:
            logger.debug("duplicate update dropped key=%s", key)
            callback: CallbackQuery | None = None
            if isinstance(event, Update):
                callback = event.callback_query
            elif isinstance(event, CallbackQuery):
                callback = event
            if callback is not None:
                with contextlib.suppress(Exception):
                    await callback.answer()
            return None

        return await handler(event, data)

    def _make_key(self, event: TelegramObject) -> Tuple[int | None, int | None, str | None] | None:
        update_id: int | None = None
        user_id: int | None = None
        callback_data: str | None = None

        if isinstance(event, Update):
            update_id = event.update_id
            if event.callback_query:
                callback = event.callback_query
                user_id = getattr(callback.from_user, "id", None)
                callback_data = callback.data
            elif event.message:
                message = event.message
                user_id = getattr(message.from_user, "id", None)
        elif isinstance(event, CallbackQuery):
            callback = event
            user_id = getattr(callback.from_user, "id", None)
            callback_data = callback.data
        elif isinstance(event, Message):
            message = event
            user_id = getattr(message.from_user, "id", None)
        else:
            return None

        if update_id is None and user_id is None and callback_data is None:
            return None

        return (update_id, user_id, callback_data or None)

    def _purge(self, now: float) -> None:
        if not self._cache:
            return
        expire_before = now - self._ttl
        keys_to_remove: list[Tuple[int | None, int | None, str | None]] = []
        for key, ts in self._cache.items():
            if ts < expire_before:
                keys_to_remove.append(key)
            else:
                break
        for key in keys_to_remove:
            self._cache.pop(key, None)

    def _shrink(self) -> None:
        while len(self._cache) > self._maxsize:
            try:
                self._cache.popitem(last=False)
            except KeyError:
                break


__all__ = ["UpdateDeduplicateMiddleware"]
