"""Repository helpers for user profile data."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile


async def get(session: AsyncSession, user_id: int) -> UserProfile | None:
    return await session.get(UserProfile, user_id)


async def get_or_create(session: AsyncSession, user_id: int) -> UserProfile:
    profile = await get(session, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, plan_json=None)
        session.add(profile)
        await session.flush()
    return profile


async def save_plan(session: AsyncSession, user_id: int, plan_json: dict[str, Any] | None) -> UserProfile:
    profile = await get_or_create(session, user_id)
    profile.plan_json = plan_json
    await session.flush()
    return profile


async def get_plan(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    profile = await get(session, user_id)
    if profile is None:
        return None
    return profile.plan_json
