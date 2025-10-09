from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.quiz.engine import load_quiz
from app.repo import events as events_repo, users as users_repo
from app.storage import commit_safely

router = Router(name="share")


async def _ref_link(bot, user_id: int) -> str:
    me = await bot.get_me()
    username = me.username or "your_bot"
    return f"https://t.me/{username}?start=ref_{user_id}"


def _share_keyboard(text: str, link: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📣 Поделиться", switch_inline_query=text)
    kb.button(text="🔗 Реф. ссылка", url=link)
    kb.button(text="📋 Скопировать", callback_data="share:copy")
    kb.adjust(1, 1, 1)
    return kb


@router.message(Command("share_result"))
async def share_result_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    async with compat_session(session_scope) as session:
        event = await events_repo.last_by(session, user.id, "quiz_finish")
        await users_repo.get_or_create_user(session, user.id, user.username)
        if event:
            await events_repo.log(session, user.id, "share_result_open", {"quiz": event.meta.get("quiz")})
        await commit_safely(session)
    if not event:
        await message.answer("Пока нечем делиться — пройди любой тест и получи результат.")
        return

    meta = event.meta or {}
    quiz_slug = meta.get("quiz") or "energy"
    try:
        quiz = load_quiz(quiz_slug)
        quiz_title = quiz.title
    except Exception:
        quiz_title = quiz_slug
    level = meta.get("level") or "—"
    summary = (
        f"Я прошёл тест «{quiz_title}» в MITO и получил уровень {level}!"
    )
    link = await _ref_link(message.bot, user.id)
    share_text = f"{summary}\nПрисоединяйся: {link}"
    kb = _share_keyboard(share_text, link).as_markup()
    lines = [
        "📣 <b>Поделиться результатом</b>",
        f"Тест: {quiz_title}",
        f"Уровень: {level}",
        "",
        "Текст для шаринга:",
        share_text,
    ]
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "share:copy")
async def share_copy(callback: CallbackQuery) -> None:
    await callback.answer("Скопируй текст из сообщения и поделись!", show_alert=False)
