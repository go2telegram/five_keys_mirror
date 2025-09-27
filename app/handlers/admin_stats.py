from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from datetime import datetime, timedelta, timezone
from io import StringIO
import csv

from app.config import settings
from app.storage_sqlite import get_session
from app.db.models import User, Subscription, Referral, PromoUsage, Event

router = Router()

def _utcnow(): return datetime.now(timezone.utc)

def _range_for(period: str):
    now = _utcnow()
    period = (period or "").lower()
    if period in ("7d","7","week"):
        return now - timedelta(days=7), now
    if period in ("30d","30","month"):
        return now - timedelta(days=30), now
    if period in ("today","1d"):
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    # default: all time
    return None, None

@router.message(Command("admin_stats"))
async def admin_stats(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    args = (m.text or "").split()[1:]
    period = args[0] if args else ""
    date_from, date_to = _range_for(period)

    with get_session() as s:
        q_users = s.query(User)
        q_subs  = s.query(Subscription)
        q_ref   = s.query(Referral)
        q_promo = s.query(PromoUsage)

        if date_from and date_to:
            q_users = q_users.filter(User.created.between(date_from, date_to))
            q_ref   = q_ref.filter(Referral.joined_at.between(date_from, date_to))
            q_promo = q_promo.filter(PromoUsage.used_at.between(date_from, date_to))

        total_users = q_users.count()
        active_subs = q_subs.count()
        conv = q_ref.filter(Referral.converted_at.isnot(None)).count()

        # топ рефереров
        raw = s.query(Referral.referrer_id, Referral.bonus_days).all()
        agg = {}
        for rid, bonus in raw:
            d = agg.setdefault(rid, {"bonus": 0, "cnt": 0})
            d["bonus"] += (bonus or 0); d["cnt"] += 1
        top = sorted(agg.items(), key=lambda kv: (kv[1]["bonus"], kv[1]["cnt"]), reverse=True)[:10]

    lines = [
        f" <b>Статистика</b> (period: <code>{period or 'all'}</code>)",
        f"ользователей: <b>{total_users}</b>",
        f"ктивных подписок: <b>{active_subs}</b>",
        f"онверсий (рефералы): <b>{conv}</b>",
        "",
        " <b>Топ рефереров</b> (id  бонусные дни  приглашено):"
    ]
    for rid, d in top:
        lines.append(f" <code>{rid}</code>  {d['bonus']}  {d['cnt']}")

    lines.append("\nкспорт CSV: /admin_export " + (period or "all"))
    await m.answer("\n".join(lines))

@router.message(Command("admin_export"))
async def admin_export(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    args = (m.text or "").split()[1:]
    period = args[0] if args else ""
    date_from, date_to = _range_for(period)

    with get_session() as s:
        q = s.query(Subscription.user_id, Subscription.plan, Subscription.since, Subscription.until)
        rows = q.all()

        # CSV  подписки
        buff = StringIO()
        w = csv.writer(buff, delimiter=";")
        w.writerow(["user_id","plan","since","until"])
        for r in rows:
            w.writerow([r.user_id, r.plan, r.since, r.until])

    data = buff.getvalue().encode("utf-8")
    fname = f"subs_{period or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path = f"./{fname}"
    with open(path, "wb") as f:
        f.write(data)
    await m.answer_document(FSInputFile(path), caption=f"кспорт подписок (period: {period or 'all'})")
