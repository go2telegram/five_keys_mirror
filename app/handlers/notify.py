# app/handlers/notify.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.db.session import session_scope
from app.repo import events as events_repo

router = Router()


@router.message(Command("notify_on"))
async def notify_on(m: Message):
    async with session_scope() as session:
        await events_repo.log(session, m.from_user.id, "notify_on", {})
        await session.commit()
    await m.answer("🔔 Напоминания включены. Буду присылать 1–2 раза в неделю.")


@router.message(Command("notify_off"))
async def notify_off(m: Message):
    async with session_scope() as session:
        await events_repo.log(session, m.from_user.id, "notify_off", {})
        await session.commit()
    await m.answer("🔕 Напоминания выключены. Включить снова: /notify_on")


@router.message(Command("notify"))
async def notify_help(m: Message):
    async with session_scope() as session:
        last_status = await events_repo.last_by(session, m.from_user.id, "notify_on")
        last_off = await events_repo.last_by(session, m.from_user.id, "notify_off")

    if last_status and (not last_off or last_status.ts > last_off.ts):
        status = "включены"
    else:
        status = "выключены"
    await m.answer(
        f"Сейчас напоминания {status}.\n\n"
        "Команды:\n"
        "• /notify_on — включить\n"
        "• /notify_off — выключить"
    )
