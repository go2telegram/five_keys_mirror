# app/handlers/referral/referral.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timezone

from app.storage import ensure_user, get_user, save_event

router = Router()


def _now(): return datetime.now(timezone.utc)


async def _ref_link(bot, user_id: int) -> str:
    me = await bot.get_me()
    uname = me.username or "your_bot"
    return f"https://t.me/{uname}?start=ref_{user_id}"


def _kb_ref(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Поделиться ссылкой", url=link)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "ref:menu")
async def ref_menu_cb(c: CallbackQuery):
    uid = c.from_user.id
    profile, _ = await ensure_user(uid)
    link = await _ref_link(c.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(profile.ref_users)}</b>\n"
        f"Уникальных переходов: <b>{profile.ref_clicks}</b>\n"
        f"Оплат (конверсий): <b>{profile.ref_conversions}</b>\n\n"
        "Поделитесь ссылкой — когда друг оформит подписку, я засчитаю конверсию."
    )
    await c.message.edit_text(text, reply_markup=_kb_ref(link))


@router.message(Command("ref"))
async def ref_menu_msg(m: Message):
    uid = m.from_user.id
    profile, _ = await ensure_user(uid)
    link = await _ref_link(m.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(profile.ref_users)}</b>\n"
        f"Уникальных переходов: <b>{profile.ref_clicks}</b>\n"
        f"Оплат (конверсий): <b>{profile.ref_conversions}</b>\n"
    )
    await m.answer(text, reply_markup=_kb_ref(link))
    profile = await get_user(uid)
    await save_event(uid, profile.source if profile else None, "ref_menu")
