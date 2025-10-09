from __future__ import annotations

import inspect
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile


async def get(session: AsyncSession, user_id: int) -> Optional[Profile]:
    getter = getattr(session, "get", None)
    if getter is None or not callable(getter):  # pragma: no cover - defensive fallback
        return None
    result = getter(Profile, user_id)
    if inspect.isawaitable(result):
        return await result
    return result


async def upsert(
    session: AsyncSession,
    user_id: int,
    *,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Profile:
    profile = await get(session, user_id)
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)

    if phone is not None:
        profile.phone = phone
    if email is not None:
        profile.email = email

    await session.flush()
    return profile


async def delete(session: AsyncSession, user_id: int) -> None:
    profile = await get(session, user_id)
    if profile is not None:
        await session.delete(profile)
        await session.flush()
