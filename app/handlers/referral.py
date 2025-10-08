from app.storage import commit_safely
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import events as events_repo, referrals as referrals_repo, users as users_repo
from app.utils import safe_edit_text

router = Router()


def _kb_ref(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Поделиться ссылкой", url=link)
    kb.button(text="📋 Скопировать", callback_data="ref:copy")
    for row in kb_back_home("ref:menu").inline_keyboard:
        kb.row(*row)
    kb.adjust(1, 1, 2)
    return kb.as_markup()


async def _ref_link(bot, user_id: int) -> str:
    me = await bot.get_me()
    uname = me.username or "your_bot"
    return f"https://t.me/{uname}?start=ref_{user_id}"


@router.callback_query(F.data == "ref:menu")
async def ref_menu_cb(c: CallbackQuery):
    uid = c.from_user.id
    username = c.from_user.username
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, uid, username)
        invited, converted = await referrals_repo.stats_for_referrer(session, uid)
        await events_repo.log(session, uid, "ref_link_open", {})
        await commit_safely(session)

    link = await _ref_link(c.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{invited}</b>\n"
        f"Оплат (конверсий): <b>{converted}</b>\n\n"
        "Поделитесь ссылкой — когда друг оформит подписку, я засчитаю конверсию."
    )
    await c.answer()
    await safe_edit_text(c.message, text, _kb_ref(link))


@router.message(Command("ref"))
async def ref_menu_msg(m: Message):
    uid = m.from_user.id
    username = m.from_user.username
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, uid, username)
        invited, converted = await referrals_repo.stats_for_referrer(session, uid)
        await events_repo.log(session, uid, "ref_link_open", {})
        await commit_safely(session)

    link = await _ref_link(m.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{invited}</b>\n"
        f"Оплат (конверсий): <b>{converted}</b>\n"
    )
    await m.answer(text, reply_markup=_kb_ref(link))


@router.callback_query(F.data == "ref:copy")
async def ref_copy(c: CallbackQuery):
    await c.answer("Скопируйте ссылку из сообщения")
    async with compat_session(session_scope) as session:
        await events_repo.log(session, c.from_user.id, "ref_link_click", {})
        await commit_safely(session)
    link = await _ref_link(c.bot, c.from_user.id)
    kb = InlineKeyboardBuilder()
    for row in kb_back_home("ref:menu").inline_keyboard:
        kb.row(*row)
    kb.adjust(2)
    await c.message.answer(f"Ваша ссылка: {link}", reply_markup=kb.as_markup())