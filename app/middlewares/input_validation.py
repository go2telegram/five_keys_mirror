"""Middleware that normalizes incoming payloads and guards against bad input."""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.keyboards import kb_back_home

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_NEWLINE_EDGES_RE = re.compile(r" *\n *")


class InputValidationMiddleware(BaseMiddleware):
    """Normalize text/callback payloads and reject obviously bad inputs."""

    def __init__(
        self,
        *,
        max_message_length: int = 4096,
        max_callback_length: int = 64,
    ) -> None:
        super().__init__()
        self._max_message_length = max_message_length
        self._max_callback_length = max_callback_length
        self._log = logging.getLogger("input.validation")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            if not await self._validate_message(event):
                return None
        elif isinstance(event, CallbackQuery) and not await self._validate_callback(event):
            return None
        return await handler(event, data)

    async def _validate_message(self, message: Message) -> bool:
        raw_text = message.text if message.text is not None else message.caption
        if raw_text is None:
            await self._notify_empty_message(message)
            return False

        normalized = _normalize_text(raw_text)
        if not normalized:
            await self._notify_empty_message(message)
            return False
        if len(normalized) > self._max_message_length:
            await self._notify_too_long(message)
            return False

        if message.text is not None:
            object.__setattr__(message, "text", normalized)
        if message.caption is not None:
            object.__setattr__(message, "caption", normalized)
        return True

    async def _validate_callback(self, callback: CallbackQuery) -> bool:
        data = callback.data or ""
        normalized = _normalize_callback_data(data)
        if not normalized:
            await self._notify_bad_callback(callback, reason="empty")
            return False
        if len(normalized) > self._max_callback_length:
            await self._notify_bad_callback(callback, reason="too_long")
            return False
        if normalized != data:
            object.__setattr__(callback, "data", normalized)
        return True

    async def _notify_empty_message(self, message: Message) -> None:
        self._log.info("empty message received uid=%s", getattr(message.from_user, "id", None))
        await message.answer(
            "Сообщение пустое. Напишите текст или воспользуйтесь кнопками ниже.",
            reply_markup=kb_back_home(),
        )

    async def _notify_too_long(self, message: Message) -> None:
        length = len(message.text or message.caption or "")
        self._log.warning("message too long uid=%s length=%s", getattr(message.from_user, "id", None), length)
        await message.answer(
            "Сообщение слишком длинное. Отправьте короче или нажмите «Домой».",
            reply_markup=kb_back_home(),
        )

    async def _notify_bad_callback(self, callback: CallbackQuery, *, reason: str) -> None:
        self._log.warning("bad callback data reason=%s uid=%s", reason, getattr(callback.from_user, "id", None))
        await callback.answer("Запрос устарел. Нажмите «Домой».", show_alert=True)
        if callback.message is not None:
            await callback.message.answer(
                "Кажется, эта кнопка больше не работает. Выберите действие заново.",
                reply_markup=kb_back_home(),
            )


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = _NEWLINE_EDGES_RE.sub("\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_callback_data(data: str) -> str:
    normalized = data.strip()
    return normalized.replace("\u0000", "")


__all__ = ["InputValidationMiddleware"]
