# app/handlers/notify.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.storage import USERS

router = Router()


@router.message(Command("notify_on"))
async def notify_on(m: Message):
    USERS.setdefault(m.from_user.id, {})["subs"] = True
    await m.answer("🔔 Напоминания включены. Буду присылать 1–2 раза в неделю.")


@router.message(Command("notify_off"))
async def notify_off(m: Message):
    USERS.setdefault(m.from_user.id, {})["subs"] = False
    await m.answer("🔕 Напоминания выключены. Включить снова: /notify_on")


@router.message(Command("notify"))
async def notify_help(m: Message):
    subs = USERS.get(m.from_user.id, {}).get("subs")
    status = "включены" if subs else "выключены"
    await m.answer(
        f"Сейчас напоминания {status}.\n\n"
        "Команды:\n"
        "• /notify_on — включить\n"
        "• /notify_off — выключить"
    )
