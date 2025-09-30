from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def get_or_create_user(
    session: AsyncSession, user_id: int, username: Optional[str] = None
) -> User:
    user = await get_user(session, user_id)
    if user:
        if username is not None and user.username != username:
            user.username = username
            await session.flush()
        return user

    user = User(id=user_id, username=username)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        user = await get_user(session, user_id)
        if user is None:
            raise
    return user


async def set_referrer(
    session: AsyncSession, user_id: int, referrer_id: int
) -> Optional[User]:
    if user_id == referrer_id:
        return await get_user(session, user_id)
    user = await get_user(session, user_id)
    if user and user.referred_by is None:
        user.referred_by = referrer_id
        await session.flush()
    return user


async def count(session: AsyncSession) -> int:
    stmt = select(func.count(User.id))
    result = await session.execute(stmt)
    return result.scalar_one()
