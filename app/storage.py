import datetime as dt
from typing import Any, Dict, Optional, List

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[int, Dict[str, Any]] = {}  # временное состояние (квизы/кальки)
EVENTS: List[Dict[str, Any]] = []         # события атрибуции


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


# ---- Бизнес-метрики ----
# данные заглушки до подключения реального DWH
FINANCE_OPERATIONS: list[dict] = []
CUSTOMER_ACQUISITIONS: list[dict] = []
RETENTION_EVENTS: list[dict] = []


def _ensure_ts(ts: dt.datetime | str | None) -> str:
    if isinstance(ts, dt.datetime):
        return ts.isoformat()
    if isinstance(ts, str) and ts:
        return ts
    return dt.datetime.utcnow().isoformat()


def record_revenue(amount: float, user_id: int | None = None,
                   source: str | None = None,
                   ts: dt.datetime | str | None = None,
                   currency: str = "RUB") -> None:
    FINANCE_OPERATIONS.append({
        "type": "revenue",
        "amount": float(amount),
        "user_id": user_id,
        "source": source,
        "currency": currency,
        "ts": _ensure_ts(ts),
    })


def record_cost(amount: float, category: str,
                ts: dt.datetime | str | None = None,
                source: str | None = None,
                currency: str = "RUB") -> None:
    FINANCE_OPERATIONS.append({
        "type": "cost",
        "amount": float(amount),
        "category": category,
        "source": source,
        "currency": currency,
        "ts": _ensure_ts(ts),
    })


def record_acquisition(user_id: int, cost: float,
                       source: str | None = None,
                       ts: dt.datetime | str | None = None,
                       campaign: str | None = None) -> None:
    CUSTOMER_ACQUISITIONS.append({
        "user_id": user_id,
        "cost": float(cost),
        "source": source,
        "ts": _ensure_ts(ts),
        "campaign": campaign,
    })


def record_retention(user_id: int,
                     day: int,
                     active: bool,
                     ts: dt.datetime | str | None = None) -> None:
    RETENTION_EVENTS.append({
        "user_id": user_id,
        "day": int(day),
        "active": bool(active),
        "ts": _ensure_ts(ts),
    })
