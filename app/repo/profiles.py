"""Repository helpers for user profile data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile


async def get(session: AsyncSession, user_id: int) -> UserProfile | None:
    return await session.get(UserProfile, user_id)


async def get_or_create(session: AsyncSession, user_id: int) -> UserProfile:
    profile = await get(session, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, plan_json=None, utm=None)
        session.add(profile)
        await session.flush()
    return profile


async def save_plan(
    session: AsyncSession, user_id: int, plan_json: dict[str, Any] | None
) -> UserProfile:
    profile = await get_or_create(session, user_id)
    profile.plan_json = plan_json
    await session.flush()
    return profile


async def get_plan(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    profile = await get(session, user_id)
    if profile is None:
        return None
    return profile.plan_json


async def save_utm(session: AsyncSession, user_id: int, utm: Mapping[str, str]) -> UserProfile:
    """Persist UTM data for a user, filling in missing values only."""

    profile = await get_or_create(session, user_id)
    existing = dict(profile.utm or {})
    updated = False
    for key, value in utm.items():
        if not value:
            continue
        if not existing.get(key):
            existing[key] = value
            updated = True
    if updated:
        profile.utm = existing
        await session.flush()
    return profile
