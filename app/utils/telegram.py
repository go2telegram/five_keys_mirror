from __future__ import annotations

from typing import Any, Awaitable, Callable

import asyncio
import logging
import random
from functools import wraps

from aiohttp import ClientError
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import CallbackQuery, Message


FALLBACK_TEXT = "Попробуйте позже"
_DEFAULT_ATTEMPTS = 3
_BASE_DELAY = 1.5
_MAX_DELAY = 10.0
_JITTER = 0.5

_log = logging.getLogger("telegram.safe")
_PATCHED_METHODS: set[tuple[type[Any], str]] = set()


FallbackHandler = Callable[[BaseException | None], Awaitable[None] | None]
FallbackFactory = Callable[[Any, Callable[..., Awaitable[Any]], tuple[Any, ...], dict[str, Any]], FallbackHandler | None]


def _markups_equal(first: Any, second: Any) -> bool:
    if first is second:
        return True
    if first is None or second is None:
        return first is None and second is None
    try:
        return first.model_dump() == second.model_dump()
    except AttributeError:
        return first == second


async def safe_edit_text(
    message: Message | None,
    new_text: str,
    new_markup: Any | None = None,
) -> None:
    if message is None:
        return
    if message.text == new_text and _markups_equal(message.reply_markup, new_markup):
        return
    try:
        await message.edit_text(new_text, reply_markup=new_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise


def _wrap_telegram_method(
    cls: type[Any],
    method_name: str,
    fallback_factory: FallbackFactory,
) -> None:
    if (cls, method_name) in _PATCHED_METHODS:
        return

    original = getattr(cls, method_name)

    @wraps(original)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        attempts = kwargs.pop("_safe_attempts", _DEFAULT_ATTEMPTS)
        fallback_enabled = kwargs.pop("_safe_fallback", True)
        fallback: FallbackHandler | None
        if fallback_enabled:
            fallback = fallback_factory(self, original, args, kwargs)
        else:
            fallback = None

        return await _execute_with_retry(
            lambda: original(self, *args, **kwargs),
            context=f"{cls.__name__}.{method_name}",
            attempts=attempts,
            fallback=fallback,
        )

    setattr(cls, method_name, wrapped)
    _PATCHED_METHODS.add((cls, method_name))


async def _execute_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    context: str,
    attempts: int,
    fallback: FallbackHandler | None,
) -> Any:
    last_exc: BaseException | None = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return None
            last_exc = exc
            _log.warning("%s failed with bad request: %s", context, exc)
            break
        except TelegramRetryAfter as exc:
            last_exc = exc
            delay = float(exc.retry_after) + random.uniform(0, _JITTER)
        except (
            TelegramNetworkError,
            TelegramServerError,
            asyncio.TimeoutError,
            ClientError,
            OSError,
        ) as exc:
            last_exc = exc
            delay = min(_MAX_DELAY, _BASE_DELAY * (2 ** (attempt - 1))) + random.uniform(0, _JITTER)
        else:
            return None

        if attempt >= attempts:
            break

        _log.warning(
            "%s attempt %d/%d failed, retrying in %.2fs: %r",
            context,
            attempt,
            attempts,
            delay,
            last_exc,
        )
        await asyncio.sleep(delay)

    if last_exc is not None:
        _log.error("%s failed after %d attempts", context, attempts, exc_info=last_exc)
        if fallback is not None:
            try:
                await fallback(last_exc)
            except Exception:
                _log.exception("%s fallback failed", context)
    return None


async def _send_fallback_message(message: Message, text: str = FALLBACK_TEXT) -> None:
    bot = getattr(message, "bot", None)
    chat = getattr(message, "chat", None)
    if bot is None or chat is None:
        return
    try:
        await bot.send_message(chat.id, text)
    except Exception:
        _log.exception("Fallback send_message failed")


def _message_answer_fallback(
    message: Message,
    _: Callable[..., Awaitable[Any]],
    __: tuple[Any, ...],
    ___: dict[str, Any],
) -> FallbackHandler | None:
    if getattr(message, "chat", None) is None:
        return None

    async def _handler(exc: BaseException | None) -> None:  # noqa: ARG001 - context is useful for debugging
        await _send_fallback_message(message)

    return _handler


def _message_edit_fallback(
    message: Message,
    _: Callable[..., Awaitable[Any]],
    __: tuple[Any, ...],
    ___: dict[str, Any],
) -> FallbackHandler | None:
    if getattr(message, "chat", None) is None:
        return None

    async def _handler(exc: BaseException | None) -> None:  # noqa: ARG001 - context is useful for debugging
        await _send_fallback_message(message)

    return _handler


def _callback_answer_fallback(
    callback: CallbackQuery,
    _original: Callable[..., Awaitable[Any]],
    _args: tuple[Any, ...],
    _kwargs: dict[str, Any],
) -> FallbackHandler | None:
    message = getattr(callback, "message", None)
    if message is None:
        return None

    async def _handler(exc: BaseException | None) -> None:  # noqa: ARG001
        await _send_fallback_message(message)

    return _handler


def _install_error_wrappers() -> None:
    _wrap_telegram_method(Message, "answer", _message_answer_fallback)
    _wrap_telegram_method(Message, "reply", _message_answer_fallback)

    for method in ("edit_text", "edit_caption", "edit_media", "edit_reply_markup"):
        if hasattr(Message, method):
            _wrap_telegram_method(Message, method, _message_edit_fallback)

    _wrap_telegram_method(CallbackQuery, "answer", _callback_answer_fallback)


_install_error_wrappers()
