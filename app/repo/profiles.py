"""Repository helpers for user profile data."""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")


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


async def update_utm(
    session: AsyncSession,
    user_id: int,
    data: Mapping[str, str | None],
) -> UserProfile:
    profile = await get_or_create(session, user_id)
    changed = False
    for field in UTM_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if isinstance(value, str):
            value = value.strip() or None
        current = getattr(profile, field)
        if current != value:
            setattr(profile, field, value)
            changed = True
    if changed:
        await session.flush()
    return profile
