from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardBuilder, Message, TelegramObject

from app.db.session import compat_session, session_scope
from app.repo import subscriptions as subscriptions_repo, users as users_repo


def premium_only(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    setattr(handler, "__premium_only__", True)
    return handler


def _cta_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оформить Premium", callback_data="premium:buy")
    kb.button(text="ℹ️ Что входит", callback_data="premium:info")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


class PremiumMiddleware(BaseMiddleware):
    """Ensure premium-only handlers are accessible to subscribers."""

    def __init__(self, flag: str = "premium_required") -> None:
        super().__init__()
        self.flag = flag

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        required = data.get(self.flag) or getattr(handler, "__premium_only__", False)
        if not required:
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        if user is None and isinstance(event, CallbackQuery):
            user = event.from_user
        if user is None:
            return await handler(event, data)

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, user.id, user.username)
            active, _ = await subscriptions_repo.is_active(session, user.id)

        if active:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(
                "🔒 Эта функция доступна только в Premium. Используйте /buy_premium, чтобы оформить доступ.",
                reply_markup=_cta_markup(),
            )
        elif isinstance(event, CallbackQuery):
            await event.answer("Нужна Premium подписка", show_alert=True)
            if event.message:
                await event.message.answer(
                    "🔒 Эта функция доступна только в Premium.", reply_markup=_cta_markup()
                )
        return None


__all__ = ["PremiumMiddleware", "premium_only"]
