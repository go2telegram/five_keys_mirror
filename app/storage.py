import datetime as dt
import time
from typing import Any, Dict, Optional, List

# tg_id -> {subs, tz, source, asked_notify, last_plan}
USERS: Dict[int, Dict[str, Any]] = {}


class SessionStore(dict[int, Dict[str, Any]]):
    """In-memory storage for temporary conversational state.

    Several handlers rely on ``SESSIONS`` to orchestrate multi-step flows
    without using the FSM. The intent router should ignore texts that belong
    to these flows, however the handlers typically clean up the dictionary
    before the router gets a chance to inspect it. To bridge this gap we keep
    short-lived timestamps for recently touched user IDs so downstream code
    can detect that another flow has just processed the message.
    """

    _RECENT_TTL = 2.0  # seconds

    def __init__(self) -> None:  # pragma: no cover - trivial init
        super().__init__()
        self._recent: Dict[int, float] = {}

    def _touch(self, key: int) -> None:
        self._recent[key] = time.monotonic()

    def __setitem__(self, key: int, value: Dict[str, Any]) -> None:
        self._touch(key)
        super().__setitem__(key, value)

    def setdefault(
        self, key: int, default: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        self._touch(key)
        return super().setdefault(key, default)

    _SENTINEL = object()

    def pop(self, key: int, default: Any = _SENTINEL) -> Any:
        existed = key in self
        if default is self._SENTINEL:
            value = super().pop(key)
        else:
            value = super().pop(key, default)
        if existed:
            self._touch(key)
        return value

    def clear(self) -> None:
        super().clear()
        self._recent.clear()

    def was_recently_active(self, key: int) -> bool:
        """Return ``True`` if ``key`` was touched within ``_RECENT_TTL`` seconds."""

        if key in self:
            return True

        ts = self._recent.get(key)
        if ts is None:
            return False

        now = time.monotonic()
        if now - ts > self._RECENT_TTL:
            # garbage collect stale markers so the dict does not grow forever
            self._recent.pop(key, None)
            return False

        return True


SESSIONS = SessionStore()  # временное состояние (квизы/кальки)
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
