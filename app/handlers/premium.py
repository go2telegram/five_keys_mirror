from functools import wraps
from typing import Awaitable, Callable, TypeVar

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import events as events_repo, subscriptions as subscriptions_repo, users as users_repo
from app.reco.ai_reasoner import build_ai_plan
from app.storage import commit_safely
from app.utils import safe_edit_text, split_md

router = Router(name="premium")

MessageHandler = TypeVar("MessageHandler", bound=Callable[..., Awaitable[None]])


def premium_only(handler: MessageHandler) -> MessageHandler:
    @wraps(handler)
    async def wrapper(message: Message, *args, **kwargs):
        user = getattr(message, "from_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None:
            await message.answer("🔒 Команда доступна только подписчикам MITO Premium.")
            return

        async with compat_session(session_scope) as session:
            is_active, _ = await subscriptions_repo.is_active(session, user_id)

        if not is_active:
            await message.answer("🔒 Команда доступна только подписчикам MITO Premium.")
            return

        return await handler(message, *args, **kwargs)

    return wrapper  # type: ignore[return-value]

BASIC_LINKS = [
    ("МИТОlife (новости)", "https://t.me/c/1858905974/3331"),
    ("EXTRA (полипренолы)", "https://t.me/c/1858905974/5"),
    ("VITEN (иммунитет)", "https://t.me/c/1858905974/13"),
    ("TÉO GREEN (клетчатка)", "https://t.me/c/1858905974/1205"),
    ("MOBIO (метабиотик)", "https://t.me/c/1858905974/11"),
]

PRO_LINKS = BASIC_LINKS + [
    ("Экспертные эфиры", "https://t.me/c/1858905974/459"),
    ("MITOпрограмма", "https://t.me/c/1858905974/221"),
    ("Маркетинг", "https://t.me/c/1858905974/18"),
    ("ERA Mitomatrix", "https://t.me/c/1858905974/3745"),
]


def _kb_links(pairs):
    kb = InlineKeyboardBuilder()
    for title, url in pairs:
        kb.button(text=f"🔗 {title}", url=url)
    for row in kb_back_home("sub:menu").inline_keyboard:
        kb.row(*row)
    layout = [2] * (len(pairs) // 2)
    if len(pairs) % 2:
        layout.append(1)
    layout.extend([2])
    kb.adjust(*layout)
    return kb.as_markup()


@router.callback_query(F.data == "premium:menu")
async def premium_menu(c: CallbackQuery):
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)
        plan = sub.plan if sub else None
        await events_repo.log(
            session,
            c.from_user.id,
            "premium_open",
            {"active": is_active, "plan": plan},
        )
        await commit_safely(session)

    await c.answer()
    if not is_active or plan is None:
        await safe_edit_text(
            c.message,
            "🔒 Premium доступен только с активной подпиской.",
            kb_back_home("sub:menu"),
        )
        return

    if plan == "basic":
        await safe_edit_text(
            c.message,
            "💎 MITO Basic — доступ к разделам:",
            _kb_links(BASIC_LINKS),
        )
    else:
        await safe_edit_text(
            c.message,
            "💎 MITO Pro — полный доступ:",
            _kb_links(PRO_LINKS),
        )


@router.message(Command("ai_plan"))
@premium_only
async def ai_plan_cmd(m: Message):
    await m.answer("⏳ Собираю твой план на неделю…")
    text = await build_ai_plan(m.from_user.id, "7d")
    for chunk in split_md(text, 3500):
        await m.answer(chunk, parse_mode="Markdown")

    async with compat_session(session_scope) as session:
        await events_repo.log(session, m.from_user.id, "plan_generated", {"source": "command"})
        await commit_safely(session)
