from __future__ import annotations

import datetime as dt

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalculatorResult, QuizResult


async def delete_quiz_results_older_than(session: AsyncSession, before: dt.datetime) -> int:
    stmt = delete(QuizResult).where(QuizResult.created < before)
    result = await session.execute(stmt)
    return result.rowcount or 0


async def delete_calculator_results_older_than(session: AsyncSession, before: dt.datetime) -> int:
    stmt = delete(CalculatorResult).where(CalculatorResult.created < before)
    result = await session.execute(stmt)
    return result.rowcount or 0
