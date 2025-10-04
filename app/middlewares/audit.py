"""Audit middleware for logging every update."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types
from aiogram.types import CallbackQuery, Message, Update

log = logging.getLogger("audit")


class AuditMiddleware(BaseMiddleware):
    """Log every incoming update, message, or callback and surface handler errors."""

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        try:
            if isinstance(event, Update):
                if event.message:
                    user = event.message.from_user
                    log.info(
                        "MSG uid=%s uname=%s chat=%s text=%r",
                        getattr(user, "id", None),
                        getattr(user, "username", None),
                        getattr(event.message.chat, "id", None),
                        event.message.text or event.message.caption,
                    )
                elif event.callback_query:
                    callback = event.callback_query
                    user = callback.from_user
                    chat = callback.message.chat if callback.message else None
                    log.info(
                        "CB  uid=%s uname=%s chat=%s data=%r",
                        getattr(user, "id", None),
                        getattr(user, "username", None),
                        getattr(chat, "id", None) if chat else None,
                        callback.data,
                    )
            elif isinstance(event, Message):
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
                chat = event.message.chat if event.message else None
                log.info(
                    "CB  uid=%s uname=%s chat=%s data=%r",
                    getattr(user, "id", None),
                    getattr(user, "username", None),
                    getattr(chat, "id", None) if chat else None,
                    event.data,
                )
            return await handler(event, data)
        except Exception:
            log.exception("Handler error on event")
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.debug("AUDIT latency_ms=%.2f", elapsed_ms)
