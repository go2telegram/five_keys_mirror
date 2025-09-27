from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime, timezone
from app.storage import USERS

router = Router()

def _fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.fromisoformat(s)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return s

@router.message(Command("profile"))
async def profile(m: Message):
    u = USERS.setdefault(m.from_user.id, {})
    sub = u.get("subscription") or {}
    plan = (sub.get("plan") or "нет").upper()
    until = sub.get("until")

    left_days = "—"
    if until:
        try:
            dtu = datetime.fromisoformat(until)
            if dtu.tzinfo is None:
                dtu = dtu.replace(tzinfo=timezone.utc)
            delta = dtu - datetime.now(timezone.utc)
            left_days = str(max(0, delta.days))
        except Exception:
            pass

    ref_users = u.get("ref_users") or set()
    ref_clicks = int(u.get("ref_clicks", 0))
    ref_conv   = int(u.get("ref_conversions", 0))
    bonus_days = int(u.get("ref_bonus_days", 0))

    text = (
        f"👤 <b>рофиль</b>\n"
        f"Тариф: <b>{plan}</b>\n"
        f"оступ до: <code>{_fmt_dt(until)}</code> (осталось дней: <b>{left_days}</b>)\n\n"
        f"👥 ефералы:\n"
        f"• риглашено: <b>{len(ref_users)}</b>\n"
        f"• никальных переходов: <b>{ref_clicks}</b>\n"
        f"• плат: <b>{ref_conv}</b>\n"
        f"• акоплено бонусных дней: <b>{bonus_days}/90</b>\n\n"
        f"оманды: <code>/ref</code> — ссылка друга, <code>/promo</code> — промокод."
    )
    await m.answer(text)

