from __future__ import annotations

import contextlib
import logging
from collections import deque
from time import monotonic
from typing import Any, Awaitable, Callable, Deque, Dict, Tuple

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger("callback.debounce")


class CallbackDebounceMiddleware(BaseMiddleware):
    """Reject rapid duplicate callback queries from the same user."""

    def __init__(self, interval: float = 0.8) -> None:
        self.interval = max(0.0, float(interval))
        self._recent: Dict[Tuple[int | None, int | None, str], float] = {}
        self._queue: Deque[Tuple[Tuple[int | None, int | None, str], float]] = deque()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or not event.data:
            return await handler(event, data)

        user_id = getattr(event.from_user, "id", None)
        message_id = getattr(event.message, "message_id", None)
        key = (user_id, message_id, event.data)

        now = monotonic()
        self._cleanup(now)
        last_seen = self._recent.get(key)
        if last_seen is not None and now - last_seen < self.interval:
            logger.debug(
                "debounced callback uid=%s msg=%s data=%s delta=%.3f",
                key[0],
                key[1],
                key[2],
                now - last_seen,
            )
            with contextlib.suppress(Exception):
                await event.answer("Подождите…")
            return None

        self._recent[key] = now
        self._queue.append((key, now))
        return await handler(event, data)

    def _cleanup(self, now: float) -> None:
        expire_before = now - max(self.interval, 0.1) * 4
        while self._queue and self._queue[0][1] < expire_before:
            key, _ = self._queue.popleft()
            self._recent.pop(key, None)


__all__ = ["CallbackDebounceMiddleware"]
