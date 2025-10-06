import datetime as dt
from typing import Any, Dict, Optional, List

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[int, Dict[str, Any]] = {}  # временное состояние (квизы/кальки)
EVENTS: List[Dict[str, Any]] = []         # события атрибуции


def save_event(user_id: Optional[int], source: Optional[str], action: str, payload: Optional[dict] = None):
    variants: Dict[str, str] = {}
    if user_id is not None:
        user_variants = USERS.get(user_id, {}).get("variants")
        if isinstance(user_variants, dict):
            variants = dict(user_variants)

    EVENTS.append({
        "ts": dt.datetime.utcnow().isoformat(),
        "user_id": user_id,
        "source": source,
        "action": action,
        "payload": payload or {},
        "variants": variants
    })

# ---- Хелперы для PDF-плана ----


def set_last_plan(user_id: int, plan: dict):
    u = USERS.setdefault(user_id, {})
    u["last_plan"] = plan


def get_last_plan(user_id: int) -> dict | None:
    return USERS.get(user_id, {}).get("last_plan")


# ---- Лиды ----
LEADS: list[dict] = []


def add_lead(lead: dict):
    LEADS.append(lead)


def get_leads_last(n: int = 10) -> list[dict]:
    return LEADS[-n:]


def get_leads_all() -> list[dict]:
    return LEADS[:]  # копия списка (для админ-экспорта)
