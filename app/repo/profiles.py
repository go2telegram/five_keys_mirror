"""Persistence helpers for user profile metadata."""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile

ProfileDict = dict[str, Any]


async def get_profile(session: AsyncSession, user_id: int) -> UserProfile | None:
    getter = getattr(session, "get", None)
    if not callable(getter):
        return None
    result = getter(UserProfile, user_id)
    if inspect.isawaitable(result):
        return await result
    return result


async def get_profile_data(session: AsyncSession, user_id: int) -> ProfileDict | None:
    profile = await get_profile(session, user_id)
    if profile is None:
        return None
    data = profile.data or {}
    return dict(data)


async def merge_profile(session: AsyncSession, user_id: int, payload: Mapping[str, Any]) -> ProfileDict:
    profile = await get_profile(session, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id, data={})
        session.add(profile)
        data: ProfileDict = {}
    else:
        data = dict(profile.data or {})

    for key, value in payload.items():
        if value is None:
            continue
        data[str(key)] = value

    profile.data = data
    await session.flush()
    return dict(data)
