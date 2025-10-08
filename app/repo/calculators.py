from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalculatorResult


def _build_query(user_id: int) -> Select[tuple[CalculatorResult]]:
    return (
        select(CalculatorResult)
        .where(CalculatorResult.user_id == user_id)
        .order_by(CalculatorResult.created_at.desc(), CalculatorResult.id.desc())
    )


async def save(
    session: AsyncSession,
    user_id: int,
    kind: str,
    payload: Mapping[str, Any],
) -> CalculatorResult:
    record = CalculatorResult(user_id=user_id, kind=kind, payload=dict(payload))
    session.add(record)
    await session.flush()
    return record


async def get_by_user(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int | None = None,
) -> Sequence[CalculatorResult]:
    stmt = _build_query(user_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())
