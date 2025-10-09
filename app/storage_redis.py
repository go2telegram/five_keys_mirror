import asyncio
import json
import os
from typing import Any, Optional

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_redis: Optional[redis.Redis] = None


async def _conn() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def touch_throttle(user_id: int, key: str, cooldown: float) -> float:
    if user_id is None or cooldown <= 0:
        return 0.0

    client = await _conn()
    loop = asyncio.get_running_loop()
    now = loop.time()
    redis_key = f"thr:{key}:{user_id}"

    prev = await client.get(redis_key)
    if prev is not None:
        try:
            prev_time = float(prev)
        except (TypeError, ValueError):
            prev_time = 0.0
        remaining = (prev_time + cooldown) - now
        if remaining > 0:
            return remaining

    await client.set(redis_key, str(now), ex=max(int(cooldown), 1))
    return 0.0


async def session_get(user_id: int) -> dict[str, Any] | None:
    client = await _conn()
    raw = await client.get(f"sess:{user_id}")
    if raw is None:
        return None
    return json.loads(raw)


async def session_set(user_id: int, data: dict[str, Any], ttl: int = 3600) -> None:
    client = await _conn()
    await client.set(
        f"sess:{user_id}",
        json.dumps(data, ensure_ascii=False),
        ex=ttl,
    )


async def session_pop(user_id: int) -> Optional[dict[str, Any]]:
    client = await _conn()
    key = f"sess:{user_id}"
    pipe = client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return json.loads(raw) if raw else None


async def cart_get(user_id: int) -> dict[str, Any] | None:
    client = await _conn()
    raw = await client.get(f"cart:{user_id}")
    if raw is None:
        return None
    return json.loads(raw)


async def cart_set(user_id: int, data: dict[str, Any], ttl: int = 3600) -> None:
    client = await _conn()
    await client.set(
        f"cart:{user_id}",
        json.dumps(data, ensure_ascii=False),
        ex=ttl,
    )


async def cart_pop(user_id: int) -> Optional[dict[str, Any]]:
    client = await _conn()
    key = f"cart:{user_id}"
    pipe = client.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return json.loads(raw) if raw else None
