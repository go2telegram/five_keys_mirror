"""Audit middleware for logging every update."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types
from aiogram.types import CallbackQuery, Message, Update

log = logging.getLogger("audit")


def _log_msg(
    update_id: int | None,
    message_id: int | None,
    user: types.User | None,
    chat_id: int | None,
    text: str | None,
) -> None:
    """Emit a consistent message log entry."""

    log.info(
        "MSG update=%s msg_id=%s uid=%s uname=%s chat=%s text=%r",
        update_id,
        message_id,
        getattr(user, "id", None),
        getattr(user, "username", None),
        chat_id,
        text,
    )


def _log_cb(
    update_id: int | None,
    callback: CallbackQuery,
    chat_id: int | None,
) -> None:
    """Emit a consistent callback log entry."""

    user = callback.from_user if callback else None
    log.info(
        "CB  update=%s msg_id=%s cb_id=%s uid=%s uname=%s chat=%s data=%r",
        update_id,
        getattr(callback.message, "message_id", None) if callback else None,
        getattr(callback, "id", None) if callback else None,
        getattr(user, "id", None),
        getattr(user, "username", None),
        chat_id,
        callback.data if callback else None,
    )


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
                log.info(
                    "UPD kind=Update update_id=%s has_msg=%s has_cb=%s",
                    event.update_id,
                    bool(event.message),
                    bool(event.callback_query),
                )
                if event.message:
                    _log_msg(
                        event.update_id,
                        event.message.message_id,
                        event.message.from_user,
                        getattr(event.message.chat, "id", None),
                        event.message.text or event.message.caption,
                    )
                elif event.callback_query:
                    callback = event.callback_query
                    chat_id = getattr(callback.message.chat, "id", None) if callback.message else None
                    _log_cb(event.update_id, callback, chat_id)
            elif isinstance(event, Message):
                _log_msg(
                    None,
                    event.message_id,
                    event.from_user,
                    getattr(event.chat, "id", None),
                    event.text or event.caption,
                )
            elif isinstance(event, CallbackQuery):
                chat_id = getattr(event.message.chat, "id", None) if event.message else None
                _log_cb(None, event, chat_id)
            return await handler(event, data)
        except Exception:
            log.exception("Handler error on event")
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log.debug("AUDIT latency_ms=%.2f", elapsed_ms)
