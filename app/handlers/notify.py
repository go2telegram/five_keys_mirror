# app/handlers/notify.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.storage import ensure_user, user_get, user_set

router = Router()


@router.message(Command("notify_on"))
async def notify_on(m: Message):
    profile = await ensure_user(m.from_user.id, {"subs": False})
    profile["subs"] = True
    await user_set(m.from_user.id, profile)
    await m.answer("🔔 Напоминания включены. Буду присылать 1–2 раза в неделю.")


@router.message(Command("notify_off"))
async def notify_off(m: Message):
    profile = await ensure_user(m.from_user.id, {"subs": False})
    profile["subs"] = False
    await user_set(m.from_user.id, profile)
    await m.answer("🔕 Напоминания выключены. Включить снова: /notify_on")


@router.message(Command("notify"))
async def notify_help(m: Message):
    profile = await user_get(m.from_user.id)
    subs = profile.get("subs")
    status = "включены" if subs else "выключены"
    await m.answer(
        f"Сейчас напоминания {status}.\n\n"
        "Команды:\n"
        "• /notify_on — включить\n"
        "• /notify_off — выключить"
    )
