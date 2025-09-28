from aiogram import Router, types
from aiogram.filters import CommandStart
from app.storage import ensure_user, set_referrer, USERS

router = Router()

@router.message(CommandStart())
async def start_cmd(m: types.Message):
    """
    /start [payload]
    payload может быть вида ref_123
    """
    ensure_user(m.from_user.id, m.from_user.username)
    payload = (m.text or "").split(maxsplit=1)
    payload = payload[1] if len(payload) > 1 else ""

    # обработка реферала
    if payload.startswith("ref_"):
        try:
            ref_id = int(payload.replace("ref_", "").strip())
            if ref_id and ref_id != m.from_user.id:
                USERS.setdefault(m.from_user.id, {})["referred_by"] = ref_id
                set_referrer(m.from_user.id, ref_id)
                await m.answer(" тметила, что вы пришли по рекомендации. Спасибо!")
            else:
                await m.answer("отово! ")
        except Exception:
            await m.answer("отово! ")
        return

    await m.answer("ривет!  на связи ")
