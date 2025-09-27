# app/handlers/referral.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timezone

from app.storage import USERS, save_event

router = Router()


def _now(): return datetime.now(timezone.utc)


async def _ref_link(bot, user_id: int) -> str:
    me = await bot.get_me()
    uname = me.username or "your_bot"
    return f"https://t.me/{uname}?start=ref_{user_id}"


def _ensure_ref_fields(uid: int):
    u = USERS.setdefault(uid, {})
    u.setdefault("ref_code", str(uid))
    u.setdefault("referred_by", None)
    u.setdefault("ref_clicks", 0)       # уникальные входы по ссылке
    # подтверждённые регистрации (первый /start)
    u.setdefault("ref_joins", 0)
    u.setdefault("ref_conversions", 0)  # оплатившие (из вебхука)
    u.setdefault("ref_users", set())    # set(uid) приглашённых (в памяти)


def _kb_ref(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Поделиться ссылкой", url=link)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "ref:menu")
async def ref_menu_cb(c: CallbackQuery):
    uid = c.from_user.id
    _ensure_ref_fields(uid)
    link = await _ref_link(c.bot, uid)
    u = USERS[uid]
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(u['ref_users'])}</b>\n"
        f"Уникальных переходов: <b>{u['ref_clicks']}</b>\n"
        f"Оплат (конверсий): <b>{u['ref_conversions']}</b>\n\n"
        "Поделитесь ссылкой — когда друг оформит подписку, я засчитаю конверсию."
    )
    await c.message.edit_text(text, reply_markup=_kb_ref(link))


@router.message(Command("ref"))
async def ref_menu_msg(m: Message):
    uid = m.from_user.id
    _ensure_ref_fields(uid)
    link = await _ref_link(m.bot, uid)
    u = USERS[uid]
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(u['ref_users'])}</b>\n"
        f"Уникальных переходов: <b>{u['ref_clicks']}</b>\n"
        f"Оплат (конверсий): <b>{u['ref_conversions']}</b>\n"
    )
    await m.answer(text, reply_markup=_kb_ref(link))
    save_event(uid, USERS.get(uid, {}).get("source"), "ref_menu")
