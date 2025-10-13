from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputFile

logger = logging.getLogger(__name__)

Step = Callable[[], Awaitable[Any]] | Awaitable[Any]


class ChatSender:
    """Coordinate sequential message delivery per chat."""

    def __init__(self, bot: Bot | None = None) -> None:
        self._bot = bot
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    def _resolve_bot(self) -> Bot:
        bot = self._bot or Bot.get_current()
        if bot is None:
            raise RuntimeError("ChatSender requires an active Bot instance")
        return bot

    async def send_sequence(self, chat_id: int, *steps: Step) -> None:
        if not steps:
            return

        lock = self._locks[chat_id]
        async with lock:
            for index, step in enumerate(steps):
                if step is None:
                    continue
                try:
                    await self._execute_step(step)
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception("send_sequence failed at step %s for chat %s", index, chat_id)
                    break

    async def _execute_step(self, step: Step) -> Any:
        if inspect.isawaitable(step):
            return await step
        if callable(step):
            result = step()
            if inspect.isawaitable(result):
                return await result
            return result
        raise TypeError(f"Unsupported step type: {type(step)!r}")

    def chat_action(self, chat_id: int, action: str) -> Step:
        async def _send() -> None:
            bot = self._resolve_bot()
            await bot.send_chat_action(chat_id, action)

        return _send

    def send_text(self, chat_id: int, text: str, **kwargs: Any) -> Step:
        async def _send():
            bot = self._resolve_bot()
            return await bot.send_message(chat_id, text, **kwargs)

        return _send

    def send_photo(
        self, chat_id: int, photo: InputFile | BufferedInputFile | bytes, **kwargs: Any
    ) -> Step:
        async def _send():
            bot = self._resolve_bot()
            return await bot.send_photo(chat_id, photo, **kwargs)

        return _send

    def send_document(
        self, chat_id: int, document: InputFile | BufferedInputFile | bytes, **kwargs: Any
    ) -> Step:
        async def _send():
            bot = self._resolve_bot()
            return await bot.send_document(chat_id, document, **kwargs)

        return _send


chat_sender = ChatSender()


__all__ = ["ChatSender", "chat_sender"]
