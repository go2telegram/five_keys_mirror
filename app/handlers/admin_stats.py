from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import settings
from app.storage_sqlite import stats_summary, top_referrers

router = Router()

@router.message(Command("admin_stats"))
async def admin_stats(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    s = stats_summary()
    top = top_referrers(10)
    lines = [
        " <b>Статистика</b>",
        f"ользователей: <b>{s['users']}</b>",
        f"ктивных подписок: <b>{s['active_subs']}</b>",
        f"онверсий (рефералы): <b>{s['conversions']}</b>",
        "",
        " <b>Топ рефереров</b> (referrer_id  бонусные дни  приглашено):"
    ]
    for row in top:
        lines.append(f" <code>{row['referrer_id']}</code>  {row['bonus_days']}  {row['invited']}")
    await m.answer("\n".join(lines))
