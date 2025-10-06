from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart

from app.texts import WELCOME, ASK_NOTIFY, NOTIFY_ON, NOTIFY_OFF
from app.keyboards import kb_main, kb_yes_no
from app.storage import (
    ensure_user,
    set_notify,
    set_asked_notify,
    add_ref_click,
    set_referred_by,
    save_event,
    get_user,
)

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    tg_id = message.from_user.id
    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    profile = await ensure_user(tg_id, source=payload or None)
    await save_event(tg_id, payload or profile.source, "start")

    # --- обработка реферального кода ---
    if payload.startswith("ref_"):
        try:
            ref_id = int(payload.split("_", 1)[1])
        except Exception:
            ref_id = None
        if ref_id and ref_id != tg_id:
            await ensure_user(ref_id)
            user_profile = await get_user(tg_id)
            new_join = user_profile.referred_by is None if user_profile else True
            await add_ref_click(ref_id, tg_id, new_join=new_join)
            if new_join:
                await set_referred_by(tg_id, ref_id)
                await save_event(tg_id, ref_id, "ref_join", {"ref_by": ref_id})

    await message.answer(WELCOME, reply_markup=kb_main())

    profile = await get_user(tg_id)
    if profile and not profile.asked_notify:
        await set_asked_notify(tg_id)
        await message.answer(ASK_NOTIFY, reply_markup=kb_yes_no("notify:yes", "notify:no"))


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    profile = await set_notify(c.from_user.id, True)
    await save_event(c.from_user.id, profile.source, "notify_on")
    await c.message.edit_text(NOTIFY_ON)


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    profile = await set_notify(c.from_user.id, False)
    await save_event(c.from_user.id, profile.source, "notify_off")
    await c.message.edit_text(NOTIFY_OFF)


@router.callback_query(F.data == "home")
async def back_home(c: CallbackQuery):
    await c.message.answer(WELCOME, reply_markup=kb_main())
