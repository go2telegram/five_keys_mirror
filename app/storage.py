"""Ephemeral in-memory helpers for FSM sessions and throttling."""

from __future__ import annotations

import inspect
import time
from collections import defaultdict
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repo import events

SESSIONS: Dict[int, Dict[str, Any]] = {}
THROTTLES: dict[str, dict[int, float]] = defaultdict(dict)
ACCESS_ROLES: dict[int, set[str]] = defaultdict(set)


async def set_last_plan(session: AsyncSession, user_id: int, plan: Dict[str, Any]) -> None:
    await events.log(session, user_id, "plan_generated", plan)


async def get_last_plan(session: AsyncSession, user_id: int) -> Dict[str, Any] | None:
    event = await events.last_by(session, user_id, "plan_generated")
    if event:
        return event.meta
    return None


async def commit_safely(session: Any) -> None:
    """Commit the session if it exposes a commit method."""

    commit = getattr(session, "commit", None)
    if commit is None:
        return
    try:
        result = commit()
    except TypeError:
        return
    if inspect.isawaitable(result):
        await result


def touch_throttle(user_id: int, key: str, cooldown: float) -> float:
    """Return remaining cooldown for the key and update the throttle bucket."""

    if user_id is None or cooldown <= 0:
        return 0.0

    now = time.monotonic()
    bucket = THROTTLES[key]
    last = bucket.get(user_id, 0.0)
    remaining = (last + cooldown) - now
    if remaining > 0:
        return remaining
    bucket[user_id] = now
    return 0.0


def grant_role(user_id: int, role: str) -> None:
    if user_id is None or not role:
        return
    ACCESS_ROLES[user_id].add(role)


def revoke_role(user_id: int, role: str) -> None:
    if user_id is None or not role:
        return
    roles = ACCESS_ROLES.get(user_id)
    if not roles:
        return
    roles.discard(role)
    if not roles:
        ACCESS_ROLES.pop(user_id, None)


def has_role(user_id: int, role: str) -> bool:
    if user_id is None or not role:
        return False
    return role in ACCESS_ROLES.get(user_id, set())
