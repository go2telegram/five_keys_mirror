from __future__ import annotations

import contextlib
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger("callback.trace")

_TRACE_ENABLED = False


def set_callback_trace_enabled(enabled: bool) -> None:
    global _TRACE_ENABLED
    _TRACE_ENABLED = bool(enabled)
    logger.info("callback trace %s", "enabled" if _TRACE_ENABLED else "disabled")


def is_callback_trace_enabled() -> bool:
    return _TRACE_ENABLED


class CallbackTraceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or not is_callback_trace_enabled():
            return await handler(event, data)

        router = data.get("event_router")
        router_name = getattr(router, "name", None) or getattr(router, "__class__", None)
        handler_name = getattr(handler, "__qualname__", repr(handler))

        state: FSMContext | None = data.get("state")
        state_before = None
        if isinstance(state, FSMContext):
            with contextlib.suppress(Exception):
                state_before = await state.get_state()

        try:
            return await handler(event, data)
        finally:
            state_after = state_before
            if isinstance(state, FSMContext):
                with contextlib.suppress(Exception):
                    state_after = await state.get_state()

            logger.info(
                "callback handled uid=%s msg=%s data=%r router=%s handler=%s state_before=%s state_after=%s",
                getattr(event.from_user, "id", None),
                getattr(event.message, "message_id", None),
                event.data,
                router_name,
                handler_name,
                state_before,
                state_after,
            )


__all__ = [
    "CallbackTraceMiddleware",
    "is_callback_trace_enabled",
    "set_callback_trace_enabled",
]
