"""Audit middleware for logging every update."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import types
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery, Message

log = logging.getLogger("audit")


class AuditMiddleware(BaseMiddleware):
    """Log every incoming message or callback and surface handler errors."""

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        try:
            if isinstance(event, Message):
                user = event.from_user
                log.info(
                    "MSG uid=%s uname=%s chat=%s text=%r",
                    getattr(user, "id", None),
                    getattr(user, "username", None),
                    getattr(event.chat, "id", None),
                    event.text or event.caption,
                )
            elif isinstance(event, CallbackQuery):
                user = event.from_user
                chat = getattr(event.message, "chat", None) if event.message else None
                chat_id = getattr(chat, "id", None)
                log.info(
                    "CB  uid=%s uname=%s chat=%s data=%r",
                    getattr(user, "id", None),
                    getattr(user, "username", None),
                    chat_id,
                    event.data,
                )
            return await handler(event, data)
        except Exception:
            log.exception("Handler error on event")
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.debug("AUDIT latency_ms=%.2f", elapsed_ms)
