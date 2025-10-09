from __future__ import annotations

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CalculatorResult,
    Event,
    Lead,
    Profile,
    PromoUsage,
    QuizResult,
    Referral,
    Subscription,
    User,
)


async def erase_user(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(Event).where(Event.user_id == user_id))
    await session.execute(delete(Lead).where(Lead.user_id == user_id))
    await session.execute(delete(PromoUsage).where(PromoUsage.user_id == user_id))
    await session.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await session.execute(
        delete(Referral).where(or_(Referral.user_id == user_id, Referral.invited_id == user_id))
    )
    await session.execute(delete(Profile).where(Profile.user_id == user_id))
    await session.execute(delete(QuizResult).where(QuizResult.user_id == user_id))
    await session.execute(delete(CalculatorResult).where(CalculatorResult.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
