from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from sqlalchemy import case, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription, User


def _normalized_utm_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _apply_utm(user: User, utm: Mapping[str, str], *, overwrite: bool = False) -> None:
    if not utm:
        return
    for key, attr in (
        ("utm_source", "utm_source"),
        ("utm_medium", "utm_medium"),
        ("utm_campaign", "utm_campaign"),
    ):
        new_value = _normalized_utm_value(utm.get(key))
        if not new_value:
            continue
        current = getattr(user, attr)
        if current and not overwrite:
            continue
        setattr(user, attr, new_value)


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str] = None,
    *,
    utm: Mapping[str, str] | None = None,
) -> User:
    user = await get_user(session, user_id)
    if user:
        if username is not None and user.username != username:
            user.username = username
            await session.flush()
        if utm:
            _apply_utm(user, utm)
            await session.flush()
        return user

    user = User(id=user_id, username=username)
    if utm:
        _apply_utm(user, utm, overwrite=True)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        user = await get_user(session, user_id)
        if user is None:
            raise
        if utm:
            _apply_utm(user, utm)
            await session.flush()
    return user


async def set_utm(
    session: AsyncSession,
    user_id: int,
    utm: Mapping[str, str],
    *,
    overwrite: bool = False,
) -> User:
    user = await get_or_create_user(session, user_id)
    _apply_utm(user, utm, overwrite=overwrite)
    await session.flush()
    return user


async def set_referrer(session: AsyncSession, user_id: int, referrer_id: int) -> Optional[User]:
    if user_id == referrer_id:
        return await get_user(session, user_id)
    user = await get_user(session, user_id)
    if user and user.referred_by is None:
        user.referred_by = referrer_id
        await session.flush()
    return user


async def count(session: AsyncSession, q: Optional[str] = None) -> int:
    stmt = select(func.count(User.id))
    if q:
        stmt = stmt.where(_search_condition(q))
    result = await session.execute(stmt)
    return result.scalar_one()


async def find(session: AsyncSession, q: Optional[str], limit: int, offset: int) -> list[User]:
    stmt = select(User).order_by(User.created.desc()).limit(limit).offset(offset)
    if q:
        stmt = stmt.where(_search_condition(q))
    result = await session.execute(stmt)
    return list(result.scalars())


async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def utm_summary(session: AsyncSession):
    now = func.now()
    active_case = case(
        (
            (Subscription.status == "active")
            & (Subscription.until > now),
            1,
        ),
        else_=0,
    )
    stmt = (
        select(
            func.coalesce(User.utm_source, "—"),
            func.coalesce(User.utm_medium, "—"),
            func.coalesce(User.utm_campaign, "—"),
            func.count(User.id),
            func.coalesce(func.sum(active_case), 0),
        )
        .select_from(User)
        .outerjoin(Subscription, Subscription.user_id == User.id)
        .group_by(User.utm_source, User.utm_medium, User.utm_campaign)
        .order_by(
            func.count(User.id).desc(),
            func.coalesce(User.utm_source, "—").asc(),
        )
    )
    result = await session.execute(stmt)
    return [
        {
            "utm_source": row[0],
            "utm_medium": row[1],
            "utm_campaign": row[2],
            "users": int(row[3] or 0),
            "premium": int(row[4] or 0),
        }
        for row in result.all()
    ]


def _search_condition(q: str):
    q = q.strip()
    conditions = []
    if not q:
        return true()
    if q.isdigit():
        conditions.append(User.id == int(q))
    like = f"%{q.lower()}%"
    username_expr = func.lower(func.coalesce(User.username, ""))
    conditions.append(username_expr.like(like))
    return or_(*conditions)
