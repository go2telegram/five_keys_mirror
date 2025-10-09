"""Simple flood protection middleware."""

from __future__ import annotations

import collections
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Deque, Dict, Iterable, Tuple

from aiogram import BaseMiddleware, types
from aiogram.types import CallbackQuery, Message


class RateLimitMiddleware(BaseMiddleware):
    """Limit incoming messages per user within a sliding time window."""

    def __init__(
        self,
        *,
        default_limit: int = 10,
        interval_seconds: float = 30.0,
        command_limits: Dict[str, Tuple[int, float]] | None = None,
        whitelist: Iterable[int] | None = None,
    ) -> None:
        self._default_limit = default_limit
        self._interval = interval_seconds
        self._command_limits = {k.lower(): v for k, v in (command_limits or {}).items()}
        self._buckets: Dict[Tuple[str, int], Deque[float]] = {}
        self._log = logging.getLogger("rate_limit")
        self._whitelist = {int(uid) for uid in (whitelist or [])}

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        if user_id is None or user_id in self._whitelist:
            return await handler(event, data)

        command = self._extract_command(event)
        if command and command in self._command_limits:
            limit, interval = self._command_limits[command]
            if not self._allow((f"cmd:{command}", user_id), limit, interval):
                await self._notify_block(event, data, interval)
                return None

        if not self._allow(("msg", user_id), self._default_limit, self._interval):
            await self._notify_block(event, data, self._interval)
            return None

        return await handler(event, data)

    def _allow(self, key: Tuple[str, int], limit: int, interval: float) -> bool:
        bucket = self._buckets.setdefault(key, collections.deque())
        now = time.monotonic()
        cutoff = now - interval
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            self._log.warning("Rate limit exceeded key=%s limit=%s interval=%s", key, limit, interval)
            return False
        bucket.append(now)
        return True

    def _extract_user_id(self, event: types.TelegramObject) -> int | None:
        if isinstance(event, Message):
            return getattr(getattr(event, "from_user", None), "id", None)
        if isinstance(event, CallbackQuery):
            return getattr(getattr(event, "from_user", None), "id", None)
        if isinstance(event, types.Update):
            if event.message:
                return self._extract_user_id(event.message)
            if event.callback_query:
                return self._extract_user_id(event.callback_query)
        return None

    def _extract_command(self, event: types.TelegramObject) -> str | None:
        if isinstance(event, Message):
            text = (event.text or event.caption or "").strip()
            if text.startswith("/"):
                command = text.split()[0].lstrip("/")
                return command.split("@", 1)[0].lower()
        return None

    async def _notify_block(
        self,
        event: types.TelegramObject,
        data: Dict[str, Any],
        interval: float,
    ) -> None:
        bot = data.get("bot")
        message = f"Слишком много запросов. Попробуйте через {int(interval)} секунд."
        if isinstance(event, Message):
            chat_id = getattr(getattr(event, "chat", None), "id", None)
            if bot and chat_id is not None:
                with suppress(Exception):
                    await bot.send_message(chat_id, message)
        elif isinstance(event, CallbackQuery):
            if bot and event.id:
                with suppress(Exception):
                    await bot.answer_callback_query(
                        callback_query_id=event.id,
                        text=message,
                        show_alert=False,
                    )
        elif isinstance(event, types.Update):
            if event.message:
                await self._notify_block(event.message, data, interval)
            elif event.callback_query:
                await self._notify_block(event.callback_query, data, interval)


__all__ = ["RateLimitMiddleware"]
