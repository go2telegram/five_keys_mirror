import datetime as dt
from typing import Any, Dict, Optional, List

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[int, Dict[str, Any]] = {}  # временное состояние (квизы/кальки)
EVENTS: List[Dict[str, Any]] = []         # события атрибуции

# Сегменты пользователей
SEGMENTS: Dict[int, str] = {}
SEGMENT_SUMMARY: Dict[str, int] = {}
SEGMENTS_UPDATED_AT: dt.datetime | None = None


def save_event(user_id: Optional[int], source: Optional[str], action: str, payload: Optional[dict] = None):
    EVENTS.append({
        "ts": dt.datetime.utcnow().isoformat(),
        "user_id": user_id,
        "source": source,
        "action": action,
        "payload": payload or {}
    })


def get_fallback_events() -> list[dict]:
    return EVENTS[:]

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


# ---- Сегментация ----


def set_segment_cache(mapping: dict[int, str], summary: dict[str, int], updated_at: dt.datetime):
    SEGMENTS.clear()
    SEGMENTS.update(mapping)

    SEGMENT_SUMMARY.clear()
    SEGMENT_SUMMARY.update(summary)

    global SEGMENTS_UPDATED_AT
    SEGMENTS_UPDATED_AT = updated_at


def get_segment_mapping() -> dict[int, str]:
    return SEGMENTS.copy()


def get_segment_summary() -> tuple[dict[str, int], dt.datetime | None]:
    return SEGMENT_SUMMARY.copy(), SEGMENTS_UPDATED_AT
