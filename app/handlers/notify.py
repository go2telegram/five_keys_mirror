# app/handlers/notify.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.storage import USERS
from app.ethics import ethics_validator, EthicsViolation

router = Router()


@router.message(Command("notify_on"))
async def notify_on(m: Message):
    try:
        ethics_validator.ensure_allowed(
            "record_opt_in_status",
            details={"user_id": m.from_user.id, "enabled": True},
        )
    except EthicsViolation:
        await m.answer("⚠️ Не могу изменить настройки: действие заблокировано политикой безопасности.")
        return

    USERS.setdefault(m.from_user.id, {})["subs"] = True
    await m.answer("🔔 Напоминания включены. Буду присылать 1–2 раза в неделю.")


@router.message(Command("notify_off"))
async def notify_off(m: Message):
    try:
        ethics_validator.ensure_allowed(
            "record_opt_in_status",
            details={"user_id": m.from_user.id, "enabled": False},
        )
    except EthicsViolation:
        await m.answer("⚠️ Не могу изменить настройки: действие заблокировано политикой безопасности.")
        return

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
