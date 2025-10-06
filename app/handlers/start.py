from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart

from app.texts import WELCOME, ASK_NOTIFY, NOTIFY_ON, NOTIFY_OFF
from app.keyboards import kb_main, kb_yes_no
from app.storage import ensure_user, save_event, user_set

router = Router()


async def _ensure_ref_fields(uid: int) -> dict:
    profile = await ensure_user(
        uid,
        {
            "subs": False,
            "tz": "Europe/Moscow",
            "source": None,
            "asked_notify": False,
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


@router.message(CommandStart())
async def start(message: Message):
    tg_id = message.from_user.id
    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    user = await ensure_user(
        tg_id,
        {"subs": False, "tz": "Europe/Moscow", "source": None, "asked_notify": False},
    )
    if payload and not user.get("source"):
        user["source"] = payload
        await user_set(tg_id, user)
    await save_event({"user_id": tg_id, "source": payload or user.get("source"), "action": "start"})
    user = await _ensure_ref_fields(tg_id)

    # --- обработка реферального кода ---
    if payload.startswith("ref_"):
        try:
            ref_id = int(payload.split("_", 1)[1])
        except Exception:
            ref_id = None
        if ref_id and ref_id != tg_id:
            ref_user = await _ensure_ref_fields(ref_id)
            if tg_id not in ref_user["ref_users"]:
                ref_user["ref_users"].append(tg_id)
                ref_user["ref_clicks"] += 1
            if user.get("referred_by") is None:
                user["referred_by"] = ref_id
                if tg_id not in ref_user["ref_users"]:
                    ref_user["ref_users"].append(tg_id)
                ref_user["ref_joins"] += 1
                await save_event(
                    {
                        "user_id": tg_id,
                        "source": ref_id,
                        "action": "ref_join",
                        "payload": {"ref_by": ref_id},
                    }
                )
            await user_set(ref_id, ref_user)
            await user_set(tg_id, user)

    await message.answer(WELCOME, reply_markup=kb_main())

    if not user.get("asked_notify"):
        user["asked_notify"] = True
        await user_set(tg_id, user)
        await message.answer(ASK_NOTIFY, reply_markup=kb_yes_no("notify:yes", "notify:no"))


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    user = await _ensure_ref_fields(c.from_user.id)
    user["subs"] = True
    await user_set(c.from_user.id, user)
    await save_event(
        {
            "user_id": c.from_user.id,
            "source": user.get("source"),
            "action": "notify_on",
        }
    )
    await c.message.edit_text(NOTIFY_ON)


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    user = await _ensure_ref_fields(c.from_user.id)
    user["subs"] = False
    await user_set(c.from_user.id, user)
    await save_event(
        {
            "user_id": c.from_user.id,
            "source": user.get("source"),
            "action": "notify_off",
        }
    )
    await c.message.edit_text(NOTIFY_OFF)


@router.callback_query(F.data == "home")
async def back_home(c: CallbackQuery):
    await c.message.answer(WELCOME, reply_markup=kb_main())
