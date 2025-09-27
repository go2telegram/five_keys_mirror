import os
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from datetime import datetime, timezone, timedelta
from app.storage import USERS

router = Router()

CODES = {c.strip().upper() for c in (os.getenv("PROMO_CODES") or "").split(",") if c.strip()}
PDF_URL = os.getenv("PROMO_PDF_URL") or ""

class PromoFSM(StatesGroup):
    wait_code = State()

def _now(): return datetime.now(timezone.utc)

def _add_days(uid: int, plan: str, days: int):
    u = USERS.setdefault(uid, {})
    sub = u.setdefault("subscription", {})
    until = sub.get("until")
    if until:
        try:
            dt = datetime.fromisoformat(until)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = _now()
    else:
        dt = _now()
    if dt < _now():
        dt = _now()
    dt = dt + timedelta(days=days)
    sub["until"] = dt.isoformat()
    sub["plan"]  = plan
    if "since" not in sub:
        sub["since"] = _now().isoformat()

@router.message(Command("promo"))
async def promo_start(m: Message, state: FSMContext):
    if not CODES:
        await m.answer("🎟 ромокоды временно не активны.")
        return
    await state.set_state(PromoFSM.wait_code)
    await m.answer("🎟 ведите промокод (без пробелов).")

@router.message(PromoFSM.wait_code)
async def promo_apply(m: Message, state: FSMContext):
    code = (m.text or "").strip().upper()
    if code not in CODES:
        await state.clear()
        await m.answer("❌ еверный или неактивный промокод.")
        return

    used = USERS.setdefault(m.from_user.id, {}).setdefault("promo_used", set())
    if code in used:
        await state.clear()
        await m.answer("ℹ️ тот промокод уже использован на вашем аккаунте.")
        return

    if code == "BASIC7":
        _add_days(m.from_user.id, "basic", 7)
        text = "✅ ромокод применён: <b>+7 дней MITO Basic</b>."
    elif code == "PRO14":
        _add_days(m.from_user.id, "pro", 14)
        text = "✅ ромокод применён: <b>+14 дней MITO Pro</b>."
    elif code == "PDF" and PDF_URL:
        text = f"✅ ромокод активирован. аш материал: {PDF_URL}"
    else:
        text = "✅ ромокод активирован."

    used.add(code)
    await state.clear()
    await m.answer(text)
