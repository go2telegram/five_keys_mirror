from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import select, update, delete
from app.db.session import get_session, init_db
from app.db.models import User, Subscription, Referral, PromoUsage, Event

# инициализация
init_db()

def _utcnow():
    return datetime.now(timezone.utc)

# -------- users / subscription --------
def ensure_user(user_id: int, username: Optional[str] = None):
    with get_session() as s:
        u = s.get(User, user_id)
        if not u:
            u = User(id=user_id, username=username)
            s.add(u)
            s.commit()
        return u

def get_subscription(user_id: int) -> Optional[dict]:
    with get_session() as s:
        sub = s.get(Subscription, user_id)
        if not sub:
            return None
        return {"plan": sub.plan, "since": sub.since.isoformat(), "until": sub.until.isoformat()}

def set_subscription(user_id: int, plan: str, since: datetime, until: datetime):
    with get_session() as s:
        ensure_user(user_id)
        sub = s.get(Subscription, user_id)
        if not sub:
            sub = Subscription(user_id=user_id, plan=plan, since=since, until=until)
            s.add(sub)
        else:
            sub.plan  = plan
            sub.since = since
            sub.until = until
        s.commit()

# -------- referrals --------
def set_referrer(invited_id: int, referrer_id: int):
    with get_session() as s:
        r = s.execute(select(Referral).where(Referral.invited_id==invited_id)).scalar_one_or_none()
        if not r:
            r = Referral(referrer_id=referrer_id, invited_id=invited_id)
            s.add(r)
            s.commit()

def mark_conversion(invited_id: int, bonus_days: int = 0):
    with get_session() as s:
        r = s.execute(select(Referral).where(Referral.invited_id==invited_id)).scalar_one_or_none()
        if r:
            r.converted_at = _utcnow()
            r.bonus_days = (r.bonus_days or 0) + bonus_days
            s.commit()

def add_bonus(referrer_id: int, days: int):
    with get_session() as s:
        # накапливаем bonus_days у всех записей рефералов данного реферера
        s.execute(update(Referral).where(Referral.referrer_id==referrer_id).values(bonus_days=Referral.bonus_days + days))
        s.commit()

# -------- promo --------
def promo_used(user_id: int, code: str) -> bool:
    with get_session() as s:
        row = s.execute(select(PromoUsage).where(PromoUsage.user_id==user_id, PromoUsage.code==code)).scalar_one_or_none()
        return row is not None

def mark_promo(user_id: int, code: str):
    with get_session() as s:
        s.add(PromoUsage(user_id=user_id, code=code))
        s.commit()

# -------- events (аналитика) --------
def save_event(user_id: int, name: str, meta: Optional[str] = None):
    with get_session() as s:
        s.add(Event(user_id=user_id, name=name, meta=meta))
        s.commit()

# -------- stats for /admin --------
def stats_summary() -> Dict[str, Any]:
    with get_session() as s:
        total_users = s.query(User).count()
        active_subs = s.query(Subscription).count()
        conv = s.query(Referral).filter(Referral.converted_at.isnot(None)).count()
        return {"users": total_users, "active_subs": active_subs, "conversions": conv}

def top_referrers(limit: int = 10):
    with get_session() as s:
        rows = s.execute(
            select(Referral.referrer_id, Referral.bonus_days)
        ).all()
        agg = {}
        for rid, bonus in rows:
            d = agg.setdefault(rid, {"bonus": 0, "cnt": 0})
            d["bonus"] += (bonus or 0)
            d["cnt"] += 1
        ordered = sorted(agg.items(), key=lambda kv: (kv[1]["bonus"], kv[1]["cnt"]), reverse=True)[:limit]
        return [{"referrer_id": rid, "bonus_days": v["bonus"], "invited": v["cnt"]} for rid, v in ordered]
