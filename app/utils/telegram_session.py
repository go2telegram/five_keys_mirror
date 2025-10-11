"""Telegram client session helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TYPE_CHECKING

import aiogram
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods.base import TelegramMethod

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from aiogram import Bot

logger = logging.getLogger("telegram.floodwait")
startup_log = logging.getLogger("startup")

SleepFunc = Callable[[float], Awaitable[None]]


def log_aiogram_version() -> None:
    """Log the currently active aiogram version for diagnostics."""

    try:
        version = aiogram.__version__
    except Exception:  # pragma: no cover - defensive fallback
        version = "unknown"
    startup_log.info("aiogram=%s (session compatibility patch active)", version)


class FloodWaitRetrySession(AiohttpSession):
    """A session that transparently retries Telegram FloodWait responses."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        sleep_func: SleepFunc | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._max_attempts = max_attempts
        self._sleep = sleep_func or asyncio.sleep

    async def make_request(
        self,
        bot: "Bot",
        method: TelegramMethod[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        kwargs.pop("timeout", None)

        attempt = 0
        while True:
            attempt += 1
            try:
                return await super().make_request(bot, method, *args, **kwargs)
            except TelegramRetryAfter as exc:
                delay = max(float(exc.retry_after), 0.0)
                method_name = getattr(method, "name", method.__class__.__name__)
                if attempt >= self._max_attempts:
                    logger.warning(
                        "FloodWait exhausted retries method=%s attempts=%s delay=%.1f",
                        method_name,
                        attempt,
                        delay,
                    )
                    raise
                logger.warning(
                    "FloodWait detected method=%s retry_after=%.1f attempt=%s/%s",
                    method_name,
                    delay,
                    attempt,
                    self._max_attempts,
                )
                await self._sleep(delay)
            except TypeError as exc:  # pragma: no cover - defensive fallback
                logger.debug("make_request fallback due to TypeError: %s", exc)
                if args or kwargs:
                    raise
                return await super().make_request(bot, method)


__all__ = ["FloodWaitRetrySession", "log_aiogram_version"]
