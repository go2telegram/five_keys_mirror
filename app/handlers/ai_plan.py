from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.middlewares.premium import premium_only
from app.reco.ai_plan import build_ai_plan
from app.repo import events as events_repo, users as users_repo
from app.storage import commit_safely

router = Router(name="ai_plan")


async def _log_request(user_id: int, horizon: str) -> None:
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, None)
        await events_repo.log(session, user_id, "ai_plan_requested", {"horizon": horizon})
        await commit_safely(session)


@router.message(Command("ai_plan"))
@premium_only
async def ai_plan_command(message: Message, command: CommandObject | None = None) -> None:
    horizon = (command.args or "7d").strip() if command and command.args else "7d"
    await _log_request(message.from_user.id, horizon)
    plan_text = await build_ai_plan(message.from_user.id, horizon=horizon)
    await message.answer(plan_text)


@router.callback_query(F.data == "ai_plan:open")
@premium_only
async def ai_plan_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    horizon = "7d"
    await _log_request(callback.from_user.id, horizon)
    plan_text = await build_ai_plan(callback.from_user.id, horizon=horizon)
    if callback.message:
        await callback.message.answer(plan_text)

