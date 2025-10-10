from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, Literal

from aiogram import BaseMiddleware, types

from app.services.runtime_metrics import runtime_metrics

__all__ = ["MetricsMiddleware"]


class MetricsMiddleware(BaseMiddleware):
    """Collect runtime metrics for updates, messages, and callbacks."""

    def __init__(self, scope: Literal["update", "message", "callback"]) -> None:
        self._scope = scope

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        try:
            if self._scope == "update" and isinstance(event, types.Update):
                runtime_metrics.record_update()
            elif self._scope == "message" and isinstance(event, types.Message):
                runtime_metrics.record_message()
            elif self._scope == "callback" and isinstance(event, types.CallbackQuery):
                runtime_metrics.record_callback()
            return await handler(event, data)
        except Exception:
            if self._scope == "update":
                runtime_metrics.record_error()
            raise
        finally:
            elapsed = max(0.0, time.perf_counter() - started)
            if self._scope == "update" and isinstance(event, types.Update):
                runtime_metrics.observe_update_duration(elapsed)
            elif self._scope == "message" and isinstance(event, types.Message):
                runtime_metrics.observe_message_duration(elapsed)
            elif self._scope == "callback" and isinstance(event, types.CallbackQuery):
                runtime_metrics.observe_callback_duration(elapsed)

    @classmethod
    def for_updates(cls) -> "MetricsMiddleware":
        return cls("update")

    @classmethod
    def for_messages(cls) -> "MetricsMiddleware":
        return cls("message")

    @classmethod
    def for_callbacks(cls) -> "MetricsMiddleware":
        return cls("callback")
