"""Repository helpers for quiz result persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuizResult


async def save(
    session: AsyncSession,
    *,
    user_id: int,
    quiz_name: str,
    score: int | None = None,
    tags: dict[str, Any] | list[Any] | None = None,
    finished_at: datetime | None = None,
) -> QuizResult:
    """Persist a new quiz result for the given user."""

    payload_tags: dict[str, Any] | list[Any]
    if tags is None:
        payload_tags = {}
    elif isinstance(tags, dict):
        payload_tags = dict(tags)
    elif isinstance(tags, list):
        payload_tags = list(tags)
    else:
        payload_tags = tags

    result = QuizResult(
        user_id=user_id,
        quiz_name=quiz_name,
        score=score,
        tags=payload_tags,
        finished_at=finished_at or datetime.now(timezone.utc),
    )
    session.add(result)
    await session.flush()
    return result


async def list_by_user(
    session: AsyncSession,
    user_id: int,
    limit: int | None = None,
) -> Sequence[QuizResult]:
    """Return quiz results for the given user ordered by recency."""

    stmt = (
        select(QuizResult)
        .where(QuizResult.user_id == user_id)
        .order_by(QuizResult.finished_at.desc(), QuizResult.id.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars())


__all__ = ["save", "list_by_user"]
