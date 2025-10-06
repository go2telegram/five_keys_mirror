import datetime as dt
from typing import Any, Dict, Optional, List

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[int, Dict[str, Any]] = {}  # временное состояние (квизы/кальки)
EVENTS: List[Dict[str, Any]] = []         # события атрибуции

# Простая in-memory модель экономики бота. Здесь копим KPI и актуальные коэффициенты
# регулирования. Всё это заменяется постоянным хранилищем в проде, но для целей
# симуляции достаточно словарей в памяти.
ECONOMY_KPI: Dict[str, float] = {
    "circulating_tokens": 1000.0,
    "target_tokens": 1000.0,
    "velocity": 1.0,
    "stability_index": 0.7,
    "utilization": 0.6,
    "engagement_index": 0.75,
}

ECONOMY_REGULATION_STATE: Dict[str, Any] = {
    "tax_rate": 0.0,
    "subsidy_rate": 0.0,
    "economic_balance": 1.0,
    "last_updated": None,
    "notes": "Регулятор пока не запускался",
}


def save_event(user_id: Optional[int], source: Optional[str], action: str, payload: Optional[dict] = None):
    EVENTS.append({
        "ts": dt.datetime.utcnow().isoformat(),
        "user_id": user_id,
        "source": source,
        "action": action,
        "payload": payload or {}
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


# ---- Экономика ----


def get_economy_kpi() -> Dict[str, float]:
    """Возвращаем копию KPI, которые собирает слой экономики."""

    return ECONOMY_KPI.copy()


def update_economy_kpi(**kwargs: float) -> None:
    """Обновление KPI (используется тестами/симуляциями)."""

    for key, value in kwargs.items():
        if key in ECONOMY_KPI:
            ECONOMY_KPI[key] = float(value)


def set_regulation_state(state: Dict[str, Any]) -> None:
    ECONOMY_REGULATION_STATE.update(state)


def get_regulation_state() -> Dict[str, Any]:
    return ECONOMY_REGULATION_STATE.copy()
