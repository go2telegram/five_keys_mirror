# app/handlers/notify.py
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.session import session_scope
from app.keyboards import kb_back_home
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

    status = "включены" if last_status and (not last_off or last_status.ts > last_off.ts) else "выключены"
    await m.answer(
        f"Сейчас напоминания {status}.\n\n" "Команды:\n" "• /notify_on — включить\n" "• /notify_off — выключить"
    )


@router.callback_query(F.data == "notify:help")
async def notify_help_cb(c: CallbackQuery):
    async with session_scope() as session:
        last_status = await events_repo.last_by(session, c.from_user.id, "notify_on")
        last_off = await events_repo.last_by(session, c.from_user.id, "notify_off")

    status = "включены" if last_status and (not last_off or last_status.ts > last_off.ts) else "выключены"

    await c.message.edit_text(
        f"Сейчас напоминания {status}.\n\n" "Команды:\n" "• /notify_on — включить\n" "• /notify_off — выключить",
        reply_markup=kb_back_home("home"),
    )
