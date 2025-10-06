from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from datetime import datetime, timezone
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.storage import ensure_user, save_event, user_set

router = Router()


def _now():
    return datetime.now(timezone.utc)


async def _ref_link(bot, user_id: int) -> str:
    me = await bot.get_me()
    uname = me.username or "your_bot"
    return f"https://t.me/{uname}?start=ref_{user_id}"


async def _ensure_ref_fields(uid: int) -> dict:
    profile = await ensure_user(
        uid,
        {
            "ref_code": str(uid),
            "referred_by": None,
            "ref_clicks": 0,
            "ref_joins": 0,
            "ref_conversions": 0,
            "ref_users": [],
        },
    )
    if not isinstance(profile.get("ref_users"), list):
        profile["ref_users"] = list(profile.get("ref_users", []))
        await user_set(uid, profile)
    return profile


def _kb_ref(link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Поделиться ссылкой", url=link)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "ref:menu")
async def ref_menu_cb(c: CallbackQuery):
    uid = c.from_user.id
    profile = await _ensure_ref_fields(uid)
    link = await _ref_link(c.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(profile['ref_users'])}</b>\n"
        f"Уникальных переходов: <b>{profile['ref_clicks']}</b>\n"
        f"Оплат (конверсий): <b>{profile['ref_conversions']}</b>\n\n"
        "Поделитесь ссылкой — когда друг оформит подписку, я засчитаю конверсию."
    )
    await c.message.edit_text(text, reply_markup=_kb_ref(link))


@router.message(Command("ref"))
async def ref_menu_msg(m: Message):
    uid = m.from_user.id
    profile = await _ensure_ref_fields(uid)
    link = await _ref_link(m.bot, uid)
    text = (
        "👥 <b>Реферальная ссылка</b>\n"
        f"{link}\n\n"
        f"Приглашённых: <b>{len(profile['ref_users'])}</b>\n"
        f"Уникальных переходов: <b>{profile['ref_clicks']}</b>\n"
        f"Оплат (конверсий): <b>{profile['ref_conversions']}</b>\n"
    )
    await m.answer(text, reply_markup=_kb_ref(link))
    await save_event({
        "user_id": uid,
        "source": profile.get("source"),
        "action": "ref_menu",
    })
