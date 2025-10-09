from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.reco.ai_reasoner import ai_tip_for_quiz
from app.repo import events as events_repo, users as users_repo
from app.storage import commit_safely
from app.utils.premium_cta import CTA_BUTTON_TEXT


async def maybe_send_free_value_drop(
    origin: CallbackQuery | Message | None,
    *,
    user_id: int,
    quiz_name: str,
    tip_tags: Sequence[str],
) -> bool:
    message: Message | None
    if isinstance(origin, CallbackQuery):
        message = origin.message
    else:
        message = origin
    if message is None:
        return False

    tip = await ai_tip_for_quiz(quiz_name, list(tip_tags))
    if not tip:
        return False

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id)
        existing = await events_repo.last_by(session, user_id, "growth_free_drop")
        if existing:
            await commit_safely(session)
            return False
        await events_repo.log(
            session,
            user_id,
            "growth_free_drop",
            {"quiz": quiz_name},
        )
        await events_repo.log(
            session,
            user_id,
            "premium_cta_show",
            {"source": "growth_drop"},
        )
        await commit_safely(session)

    builder = InlineKeyboardBuilder()
    builder.button(text=CTA_BUTTON_TEXT, callback_data="premium:cta:growth_drop")
    builder.adjust(1)
    text = (
        f"💡 {tip}\n\n"
        "Готов получить полный AI-план? Нажми кнопку ниже — откроется Premium."
    )
    await message.answer(text, reply_markup=builder.as_markup())
    return True
