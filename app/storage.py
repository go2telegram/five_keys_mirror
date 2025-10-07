"""Ephemeral in-memory helpers for FSM sessions only."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repo import events

SESSIONS: Dict[int, Dict[str, Any]] = {}


async def set_last_plan(session: AsyncSession, user_id: int, plan: Dict[str, Any]) -> None:
    await events.log(session, user_id, "plan_generated", plan)


async def get_last_plan(session: AsyncSession, user_id: int) -> Dict[str, Any] | None:
    event = await events.last_by(session, user_id, "plan_generated")
    if event:
        return event.meta
    return None
