from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime, timezone

USERS: Dict[int, Dict[str, Any]] = {}

from app.storage_sqlite import (
    ensure_user as _ensure_user,
    get_subscription as _get_subscription_db,
    set_subscription as _set_subscription_db,
    set_referrer as _set_referrer_db,
    mark_conversion as _mark_conversion_db,
    add_bonus as _add_bonus_db,
    promo_used as _promo_used_db,
    mark_promo as _mark_promo_db,
    save_event as _save_event_db,
    all_subscriptions as _all_subs_db,
)

def _utcnow() -> datetime: return datetime.now(timezone.utc)

def load_cache_from_db() -> None:
    try:
        for row in _all_subs_db():
            USERS.setdefault(row["user_id"], {})["subscription"] = {
                "plan": row["plan"], "since": row["since"], "until": row["until"]
            }
    except Exception:
        pass

load_cache_from_db()
# one-time bootstrap from cache to DB
try:
    _ = migrate_users_to_db()
except Exception:
    pass

def ensure_user(user_id: int, username: Optional[str] = None) -> None:
    _ensure_user(user_id, username)

def get_subscription(user_id: int) -> Optional[dict]:
    db = _get_subscription_db(user_id)
    if db:
        USERS.setdefault(user_id, {})["subscription"] = db
        return db
    return USERS.get(user_id, {}).get("subscription")

def set_subscription(user_id: int, plan: str, since: datetime, until: datetime) -> None:
    _set_subscription_db(user_id, plan, since, until)
    USERS.setdefault(user_id, {})["subscription"] = {
        "plan": plan, "since": since.isoformat(), "until": until.isoformat()
    }

def set_referrer(invited_id: int, referrer_id: int) -> None:
    _set_referrer_db(invited_id, referrer_id)
    u_ref = USERS.setdefault(referrer_id, {})
    u_inv = USERS.setdefault(invited_id, {})
    u_ref.setdefault("ref_users", set()).add(invited_id)
    u_ref["ref_joins"] = int(u_ref.get("ref_joins", 0)) + 1
    if u_inv.get("referred_by") is None:
        u_inv["referred_by"] = referrer_id

def mark_conversion(invited_id: int, bonus_days: int = 0) -> None:
    _mark_conversion_db(invited_id, bonus_days)
    for rid, data in USERS.items():
        if invited_id in data.get("ref_users") or USERS.get(invited_id, {}).get("referred_by") == rid:
            data["ref_conversions"] = int(data.get("ref_conversions", 0)) + 1
            if bonus_days:
                data["ref_bonus_days"] = int(data.get("ref_bonus_days", 0)) + bonus_days
            break

def add_bonus(referrer_id: int, days: int) -> None:
    _add_bonus_db(referrer_id, days)
    u = USERS.setdefault(referrer_id, {})
    u["ref_bonus_days"] = int(u.get("ref_bonus_days", 0)) + days

def promo_used(user_id: int, code: str) -> bool:
    return _promo_used_db(user_id, code)

def mark_promo(user_id: int, code: str) -> None:
    _mark_promo_db(user_id, code)

def save_event(user_id: int, source, name: str, meta: Optional[dict] = None):
    m = None
    if meta:
        try:
            import json
            m = json.dumps(meta, ensure_ascii=False)
        except Exception:
            m = str(meta)
    _save_event_db(user_id, name, m)

def migrate_users_to_db() -> int:
    """
    ереносит подписки/рефералку из текущего кэша USERS в .
    озвращает количество пользователей с мигрированными подписками.
    """
    migrated = 0
    try:
        for uid, data in USERS.items():
            sub = data.get("subscription")
            if sub and all(k in sub for k in ("plan","since","until")):
                from datetime import datetime
                since = datetime.fromisoformat(sub["since"])
                until = datetime.fromisoformat(sub["until"])
                set_subscription(uid, sub["plan"], since, until)
                migrated += 1

            # реф-история: основной referrer
            ref_by = data.get("referred_by")
            if ref_by:
                try:
                    set_referrer(uid, ref_by)
                except Exception:
                    pass
    except Exception:
        pass
    return migrated
# --- legacy session cache for handlers (calc, etc.) ---
# хранит лёгкие пользовательские состояния; не требует 
SESSIONS: Dict[int, Dict[str, Any]] = {}

def get_session(uid: int) -> Dict[str, Any]:
    """ернёт/создаст сессию пользователя (in-memory)."""
    return SESSIONS.setdefault(uid, {})

def set_last_plan(uid: int, plan: str) -> None:
    """Совместимость со старым /calc: запоминаем выбранный план."""
    s = get_session(uid)
    s["last_plan"] = plan
    # зеркалим в USERS для UI/профиля
    u = USERS.setdefault(uid, {})
    u["last_plan"] = plan

def get_last_plan(uid: int) -> Optional[str]:
    """ернёт последний выбранный план из сессии/кэша."""
    s = SESSIONS.get(uid, {})
    return s.get("last_plan") or USERS.get(uid, {}).get("last_plan")
