# app/handlers/referral.py
from datetime import timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.storage import USERS, save_event
from bot.referral_ui import build_dashboard
from growth.bonuses import get_bonus_profile
from growth.referrals import compute_viral_k, get_user_stats

router = Router()

_CHANNELS = ("organic", "stories", "reels", "newsletter")


def _ensure_ref_fields(uid: int):
    u = USERS.setdefault(uid, {})
    u.setdefault("ref_code", str(uid))
    u.setdefault("referred_by", None)
    u.setdefault("ref_clicks", 0)
    u.setdefault("ref_joins", 0)
    u.setdefault("ref_conversions", 0)
    u.setdefault("ref_users", set())
    u.setdefault("ref_channel", _CHANNELS[0])
    u.setdefault("ref_channels", {})


async def _dashboard(bot, uid: int, *, channel: str | None = None):
    _ensure_ref_fields(uid)
    user_data = USERS[uid]
    if channel:
        user_data["ref_channel"] = channel
    current_channel = user_data.get("ref_channel", _CHANNELS[0])
    me = await bot.get_me()
    username = me.username or "your_bot"
    stats = get_user_stats(uid)
    bonus = get_bonus_profile(uid)
    viral_k = compute_viral_k(window=timedelta(days=30))
    dash = build_dashboard(
        bot_username=username,
        user_id=uid,
        stats=stats,
        bonus=bonus,
        invited=len(user_data.get("ref_users", set())),
        channel=current_channel,
        viral_k=viral_k,
        channels=_CHANNELS,
    )
    return dash


@router.callback_query(F.data == "ref:menu")
async def ref_menu_cb(c: CallbackQuery):
    dash = await _dashboard(c.bot, c.from_user.id)
    await c.message.edit_text(dash.text, reply_markup=dash.keyboard)


@router.callback_query(F.data.startswith("ref:channel:"))
async def ref_select_channel(c: CallbackQuery):
    _, _, channel = c.data.partition("ref:channel:")
    dash = await _dashboard(c.bot, c.from_user.id, channel=channel)
    await c.message.edit_text(dash.text, reply_markup=dash.keyboard)


@router.message(Command("ref"))
async def ref_menu_msg(m: Message):
    dash = await _dashboard(m.bot, m.from_user.id)
    await m.answer(dash.text, reply_markup=dash.keyboard)
    save_event(m.from_user.id, USERS.get(m.from_user.id, {}).get("source"), "ref_menu")
