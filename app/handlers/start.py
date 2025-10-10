from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart

from app.texts import WELCOME, ASK_NOTIFY, NOTIFY_ON, NOTIFY_OFF
from app.keyboards import kb_main, kb_yes_no
from app.storage import USERS, save_event
from growth.referrals import decode_start_payload, log_referral_event, ReferralValidationError

router = Router()


def _ensure_ref_fields(uid: int):
    u = USERS.setdefault(uid, {})
    u.setdefault("ref_code", str(uid))
    u.setdefault("referred_by", None)
    u.setdefault("ref_clicks", 0)
    u.setdefault("ref_joins", 0)
    u.setdefault("ref_conversions", 0)
    u.setdefault("ref_users", set())
    u.setdefault("ref_channels", {})


@router.message(CommandStart())
async def start(message: Message):
    tg_id = message.from_user.id
    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    USERS.setdefault(
        tg_id, {"subs": False, "tz": "Europe/Moscow", "source": None})
    save_event(tg_id, payload, "start")
    _ensure_ref_fields(tg_id)

    # --- обработка реферального кода ---
    if payload:
        try:
            ref_code, channel = decode_start_payload(payload)
        except ReferralValidationError:
            ref_code = None
            channel = None
        if ref_code:
            try:
                ref_id = int(ref_code)
            except Exception:
                ref_id = None
            if ref_id and ref_id != tg_id:
                _ensure_ref_fields(ref_id)
                referred_first_time = tg_id not in USERS[ref_id]["ref_users"]
                if referred_first_time:
                    USERS[ref_id]["ref_clicks"] += 1
                    log_referral_event(
                        "click",
                        referrer_id=ref_id,
                        referred_id=tg_id,
                        channel=channel,
                        metadata={"source": "start"},
                    )
                if USERS[tg_id].get("referred_by") is None:
                    USERS[tg_id]["referred_by"] = ref_id
                    USERS[tg_id]["referred_channel"] = channel
                    USERS[ref_id]["ref_users"].add(tg_id)
                    USERS[ref_id]["ref_joins"] += 1
                    USERS[ref_id]["ref_channels"][tg_id] = channel
                    log_referral_event(
                        "join",
                        referrer_id=ref_id,
                        referred_id=tg_id,
                        channel=channel,
                        metadata={"source": "start"},
                    )
                save_event(tg_id, ref_id, "ref_join", {"ref_by": ref_id, "channel": channel})

    await message.answer(WELCOME, reply_markup=kb_main())

    if not USERS[tg_id].get("asked_notify"):
        USERS[tg_id]["asked_notify"] = True
        await message.answer(ASK_NOTIFY, reply_markup=kb_yes_no("notify:yes", "notify:no"))


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    USERS[c.from_user.id]["subs"] = True
    save_event(c.from_user.id, USERS[c.from_user.id].get(
        "source"), "notify_on")
    await c.message.edit_text(NOTIFY_ON)


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    USERS[c.from_user.id]["subs"] = False
    save_event(c.from_user.id, USERS[c.from_user.id].get(
        "source"), "notify_off")
    await c.message.edit_text(NOTIFY_OFF)


@router.callback_query(F.data == "home")
async def back_home(c: CallbackQuery):
    await c.message.answer(WELCOME, reply_markup=kb_main())
