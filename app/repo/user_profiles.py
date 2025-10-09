from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile


async def get(session: AsyncSession, user_id: int) -> Optional[UserProfile]:
    return await session.get(UserProfile, user_id)


async def get_or_create(session: AsyncSession, user_id: int) -> UserProfile:
    profile = await get(session, user_id)
    if profile is not None:
        return profile

    profile = UserProfile(user_id=user_id, plan_json=None, updated_at=datetime.now(timezone.utc))
    session.add(profile)
    await session.flush()
    return profile


async def update_plan(session: AsyncSession, user_id: int, payload: dict) -> UserProfile:
    profile = await get_or_create(session, user_id)
    profile.plan_json = payload
    profile.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return profile


async def recent_with_plan(session: AsyncSession, limit: int = 10) -> list[UserProfile]:
    stmt = (
        select(UserProfile)
        .where(UserProfile.plan_json.is_not(None))
        .order_by(UserProfile.updated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())
