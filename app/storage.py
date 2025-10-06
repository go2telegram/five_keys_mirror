import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_REDIS: Redis | None = None
_USERS_INDEX_KEY = "bot:users"
_EVENTS_KEY = "bot:events"
_EVENT_COUNTERS_KEY = "bot:event_counters"

_memory_users: Dict[int, Dict[str, Any]] = {}
_memory_sessions: Dict[int, Dict[str, Any]] = {}
_memory_events: List[Dict[str, Any]] = []
_memory_event_counters: Dict[str, int] = {}
_memory_leads: List[Dict[str, Any]] = []

# временное состояние (квизы/кальки) остаётся в памяти
SESSIONS = _memory_sessions


async def init_storage(redis_url: Optional[str]) -> None:
    """Инициализируем подключение к Redis, если URL задан."""
    global _REDIS
    if not redis_url:
        logger.warning("REDIS_URL is not configured; using in-memory storage")
        return

    client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
    except RedisError as exc:  # pragma: no cover - сеть/Redis
        logger.warning("Redis unavailable (%s); falling back to in-memory storage", exc)
        await client.close()
        return

    _REDIS = client
    logger.info("Redis storage initialised")


def redis_enabled() -> bool:
    return _REDIS is not None


def _user_key(user_id: int) -> str:
    return f"bot:user:{user_id}"


async def user_get(user_id: int) -> Dict[str, Any]:
    """Возвращает копию профиля пользователя."""
    data: Optional[Dict[str, Any]] = None
    if _REDIS is not None:
        try:
            raw = await _REDIS.get(_user_key(user_id))
        except RedisError as exc:  # pragma: no cover - сеть/Redis
            logger.warning("Redis GET failed for user %s: %s", user_id, exc)
        else:
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.error("Corrupted JSON for user %s", user_id)
                    data = {}

    if data is None:
        cached = _memory_users.get(user_id, {})
        return dict(cached)

    _memory_users[user_id] = data
    return dict(data)


async def user_set(user_id: int, profile: Dict[str, Any]) -> None:
    """Сохраняет профиль пользователя в Redis (при наличии) и кэш."""
    def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, set):
                normalized[key] = list(value)
            else:
                normalized[key] = value
        return normalized

    profile = _normalize(profile)
    if _REDIS is not None:
        try:
            if profile:
                await _REDIS.set(_user_key(user_id), json.dumps(profile, ensure_ascii=False))
                await _REDIS.sadd(_USERS_INDEX_KEY, str(user_id))
            else:
                await _REDIS.delete(_user_key(user_id))
                await _REDIS.srem(_USERS_INDEX_KEY, str(user_id))
        except RedisError as exc:  # pragma: no cover - сеть/Redis
            logger.warning("Redis SET failed for user %s: %s", user_id, exc)

    if profile:
        _memory_users[user_id] = dict(profile)
    else:
        _memory_users.pop(user_id, None)


async def ensure_user(user_id: int, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Возвращает профиль и дополняет его значениями по умолчанию."""
    profile = await user_get(user_id)
    changed = False
    if isinstance(profile.get("ref_users"), set):
        profile["ref_users"] = list(profile["ref_users"])
        changed = True
    if defaults:
        for key, value in defaults.items():
            if key not in profile:
                profile[key] = value
                changed = True
    if changed:
        await user_set(user_id, profile)
    return profile


async def get_all_users() -> Dict[int, Dict[str, Any]]:
    if _REDIS is None:
        return {uid: dict(data) for uid, data in _memory_users.items()}

    users: Dict[int, Dict[str, Any]] = {}
    try:
        raw_ids = await _REDIS.smembers(_USERS_INDEX_KEY)
    except RedisError as exc:  # pragma: no cover - сеть/Redis
        logger.warning("Redis SMEMBERS failed: %s", exc)
        return {uid: dict(data) for uid, data in _memory_users.items()}

    for raw in raw_ids:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        users[uid] = await user_get(uid)
    return users


async def save_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = {"ts": dt.datetime.utcnow().isoformat(), **payload}

    if _REDIS is not None:
        try:
            await _REDIS.rpush(_EVENTS_KEY, json.dumps(event, ensure_ascii=False))
            action = event.get("action")
            if action:
                await _REDIS.hincrby(_EVENT_COUNTERS_KEY, action, 1)
        except RedisError as exc:  # pragma: no cover - сеть/Redis
            logger.warning("Redis RPUSH failed: %s", exc)

    _memory_events.append(event)
    if len(_memory_events) > 1000:
        del _memory_events[:-1000]
    action = event.get("action")
    if action:
        _memory_event_counters[action] = _memory_event_counters.get(action, 0) + 1
    return event


async def events_tail(n: int) -> List[Dict[str, Any]]:
    if _REDIS is not None:
        try:
            raw_items = await _REDIS.lrange(_EVENTS_KEY, -n, -1)
        except RedisError as exc:  # pragma: no cover - сеть/Redis
            logger.warning("Redis LRANGE failed: %s", exc)
        else:
            return [json.loads(item) for item in raw_items]
    return _memory_events[-n:]


async def get_event_count(action: str) -> int:
    if _REDIS is not None:
        try:
            value = await _REDIS.hget(_EVENT_COUNTERS_KEY, action)
        except RedisError as exc:  # pragma: no cover - сеть/Redis
            logger.warning("Redis HGET failed for action %s: %s", action, exc)
        else:
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
    return _memory_event_counters.get(action, 0)


# ---- Хелперы для PDF-плана ----


async def set_last_plan(user_id: int, plan: dict) -> None:
    profile = await ensure_user(user_id, {})
    profile["last_plan"] = plan
    await user_set(user_id, profile)


async def get_last_plan(user_id: int) -> Optional[dict]:
    profile = await user_get(user_id)
    return profile.get("last_plan")


# ---- Лиды ----


def add_lead(lead: dict):
    _memory_leads.append(lead)


def get_leads_last(n: int = 10) -> List[dict]:
    return _memory_leads[-n:]


def get_leads_all() -> List[dict]:
    return list(_memory_leads)
