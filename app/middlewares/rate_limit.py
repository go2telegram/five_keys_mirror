"""Rate limiting middleware to guard bot handlers from flooding."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Iterable

from aiogram import BaseMiddleware, types
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings

RateLimit = tuple[int, float]


def _resolve_admin_ids() -> set[int]:
    admins: set[int] = set()
    if settings.ADMIN_ID:
        admins.add(int(settings.ADMIN_ID))
    extra = settings.ADMIN_USER_IDS or []
    iterator = (
        extra if isinstance(extra, Iterable) and not isinstance(extra, (str, bytes)) else [extra]
    )
    for item in iterator:
        try:
            admins.add(int(item))
        except Exception:  # pragma: no cover - defensive guard
            continue
    return {admin for admin in admins if admin}


class RateLimitMiddleware(BaseMiddleware):
    """Simple per-user rate limiter with command-specific rules."""

    def __init__(
        self,
        *,
        default_limit: RateLimit = (10, 30.0),
        command_limits: dict[str, RateLimit] | None = None,
        admin_ids: Iterable[int] | None = None,
    ) -> None:
        super().__init__()
        self._default_limit = default_limit
        self._command_limits = {
            key.lstrip("/"): value for key, value in (command_limits or {}).items()
        }
        self._admins = {int(admin) for admin in (admin_ids or _resolve_admin_ids()) if admin}
        self._buckets: dict[tuple[str, int], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._log = logging.getLogger("ratelimit")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event, data)
        if user_id is None or user_id in self._admins:
            return await handler(event, data)

        allowed, retry_after = await self._touch_bucket(("__all__", user_id), self._default_limit)
        if not allowed:
            await self._notify(event, retry_after)
            return None

        if isinstance(event, Message):
            command = self._extract_command(event)
            if command and command in self._command_limits:
                allowed, retry_after = await self._touch_bucket(
                    (command, user_id), self._command_limits[command]
                )
                if not allowed:
                    await self._notify(event, retry_after)
                    return None

        return await handler(event, data)

    async def _touch_bucket(self, key: tuple[str, int], limit: RateLimit) -> tuple[bool, float]:
        count, window = limit
        if count <= 0 or window <= 0:
            return True, 0.0
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets[key]
            while bucket and now - bucket[0] >= window:
                bucket.popleft()
            if len(bucket) >= count:
                retry_after = window - (now - bucket[0])
                self._log.warning(
                    "rate limit triggered scope=%s user=%s retry_after=%.2f",
                    key[0],
                    key[1],
                    max(retry_after, 0.0),
                )
                return False, max(retry_after, 0.0)
            bucket.append(now)
        return True, 0.0

    def _extract_user_id(self, event: TelegramObject, data: dict[str, Any]) -> int | None:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        user = data.get("event_from_user")
        if isinstance(user, types.User):
            return user.id
        return None

    def _extract_command(self, message: Message) -> str | None:
        text = message.text or message.caption or ""
        text = text.strip()
        if not text.startswith("/"):
            return None
        command = text.split()[0]
        if "@" in command:
            command = command.split("@", 1)[0]
        return command.lstrip("/").lower()

    async def _notify(self, event: TelegramObject, retry_after: float) -> None:
        seconds = max(1, math.ceil(retry_after))
        message = f"⏳ Слишком много запросов, попробуйте через {seconds} с."
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(message, show_alert=True)
            except Exception:  # pragma: no cover - best-effort notification
                self._log.debug("Failed to notify callback rate limit", exc_info=True)
            return
        if isinstance(event, Message):
            try:
                await event.answer(message)
            except Exception:
                self._log.debug("Failed to notify message rate limit", exc_info=True)


__all__ = ["RateLimitMiddleware"]
