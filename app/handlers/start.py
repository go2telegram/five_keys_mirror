from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.db.session import session_scope
from app.keyboards import kb_main, kb_yes_no
from app.repo import events as events_repo
from app.repo import referrals as referrals_repo
from app.repo import users as users_repo
from app.texts import ASK_NOTIFY, NOTIFY_OFF, NOTIFY_ON

router = Router()

START_GREETING = (
    "Привет! На связи «Пять ключей здоровья». Выбирай раздел в меню ниже:"
)


@router.message(CommandStart())
async def start(message: Message):
    tg_id = message.from_user.id
    username = message.from_user.username
    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    async with session_scope() as session:
        await users_repo.get_or_create_user(session, tg_id, username)
        await events_repo.log(session, tg_id, "start", {"payload": payload})

        if payload.startswith("ref_"):
            try:
                ref_id = int(payload.split("_", 1)[1])
            except (ValueError, IndexError):
                ref_id = None
            if ref_id and ref_id != tg_id:
                await users_repo.get_or_create_user(session, ref_id)
                existing_ref = await referrals_repo.get_by_invited(session, tg_id)
                if existing_ref is None:
                    await referrals_repo.create(session, ref_id, tg_id)
                await users_repo.set_referrer(session, tg_id, ref_id)
                await events_repo.log(session, tg_id, "ref_join", {"referrer_id": ref_id})

        already_prompted = await events_repo.last_by(session, tg_id, "notify_prompted")
        await session.commit()

    await message.answer(START_GREETING, reply_markup=kb_main())

    if not already_prompted:
        async with session_scope() as session:
            await events_repo.log(session, tg_id, "notify_prompted", {})
            await session.commit()
        await message.answer(
            ASK_NOTIFY, reply_markup=kb_yes_no("notify:yes", "notify:no")
        )


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    async with session_scope() as session:
        await events_repo.log(session, c.from_user.id, "notify_on", {})
        await session.commit()
    await c.message.edit_text(NOTIFY_ON)


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    async with session_scope() as session:
        await events_repo.log(session, c.from_user.id, "notify_off", {})
        await session.commit()
    await c.message.edit_text(NOTIFY_OFF)


@router.callback_query(F.data == "home")
async def back_home(c: CallbackQuery):
    await c.message.answer(START_GREETING, reply_markup=kb_main())
