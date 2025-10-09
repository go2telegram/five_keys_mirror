"""Handlers responsible for privacy-related commands."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db.session import compat_session, session_scope
from app.repo import privacy as privacy_repo
from app.storage import commit_safely

router = Router(name="privacy")
logger = logging.getLogger(__name__)


@router.message(Command("erase_me"))
async def erase_me(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    if user_id is None:
        await message.answer("Команда доступна только пользователям.")
        return

    async with compat_session(session_scope) as session:
        await privacy_repo.erase_user(session, user_id)
        await commit_safely(session)

    logger.info("User requested data erasure uid=%s", user_id)
    await message.answer(
        "Ваши данные, подписки и результаты тестов удалены. "
        "Если захотите вернуться — просто снова напишите /start."
    )
