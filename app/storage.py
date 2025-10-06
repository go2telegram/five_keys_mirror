import datetime as dt
from typing import Any, Dict, Optional, List

from app.config import settings

try:
    from economy import service as economy_service
except Exception:  # pragma: no cover - economy is optional in tests
    economy_service = None

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[int, Dict[str, Any]] = {}  # временное состояние (квизы/кальки)
EVENTS: List[Dict[str, Any]] = []         # события атрибуции


_REWARD_RULES: dict[str, dict[str, Any]] = {
    "start": {"amount": 10, "note": "Приветственный бонус"},
    "quiz_finish": {"amount": 25, "note": "Завершение квиза"},
    "ref_join": {"amount": 50, "note": "Приглашение друга"},
}


def _apply_economy_rewards(user_id: Optional[int], action: str):
    if not user_id or not settings.ENABLE_GLOBAL_ECONOMY:
        return
    if economy_service is None:
        return

    reward = _REWARD_RULES.get(action)
    if not reward:
        return

    amount = int(reward.get("amount", 0))
    note = str(reward.get("note", action))
    if amount <= 0:
        return

    try:
        economy_service.earn_tokens(user_id, amount, note=note)
    except Exception:
        # экономический слой не должен ронять сохранение события
        pass


def save_event(user_id: Optional[int], source: Optional[str], action: str, payload: Optional[dict] = None):
    EVENTS.append({
        "ts": dt.datetime.utcnow().isoformat(),
        "user_id": user_id,
        "source": source,
        "action": action,
        "payload": payload or {}
    })
    _apply_economy_rewards(user_id, action)

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
