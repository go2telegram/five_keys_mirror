"""Guards and decorators for handlers."""

from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable, TypeVar

from aiogram.types import Message

Handler = TypeVar("Handler", bound=Callable[..., Awaitable[Any]])

PREMIUM_REQUIRED_TEXT = (
    "💎 Доступно только для Premium. Оформи подписку, чтобы получить персональный план."
)


def _extract_entitlements(message: Message | Any, kwargs: dict[str, Any]) -> Any:
    if "entitlements" in kwargs:
        return kwargs["entitlements"]

    direct = getattr(message, "entitlements", None)
    if direct is not None:
        return direct

    bot = getattr(message, "bot", None)
    ctx = getattr(bot, "context", None)
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    if isinstance(ctx, dict) and user_id is not None:
        ent_map = ctx.get("entitlements")
        if isinstance(ent_map, dict):
            return ent_map.get(user_id)
    return None


def _has_premium(entitlements: Any) -> bool:
    if entitlements is None:
        return False
    if isinstance(entitlements, dict):
        for key in ("premium", "is_premium", "has_premium"):
            value = entitlements.get(key)
            if value:
                return bool(value)
        return False
    if isinstance(entitlements, (set, list, tuple)):
        lowered = {_normalize_flag(flag) for flag in entitlements}
        return any(flag in lowered for flag in {"premium", "premium_active", "pro"})
    for attr in ("premium", "is_premium", "has_premium"):
        if getattr(entitlements, attr, False):
            return True
    return False


def _normalize_flag(flag: Any) -> str:
    return str(flag).strip().lower()


def premium_only(handler: Handler) -> Handler:
    """Allow handler execution only for users with premium entitlement."""

    @functools.wraps(handler)
    async def wrapper(message: Message, *args: Any, **kwargs: Any):  # type: ignore[override]
        entitlements = _extract_entitlements(message, kwargs)
        if not _has_premium(entitlements):
            answer = getattr(message, "answer", None)
            if callable(answer):
                await answer(PREMIUM_REQUIRED_TEXT)
            return None
        return await handler(message, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


__all__ = ["premium_only", "PREMIUM_REQUIRED_TEXT"]
