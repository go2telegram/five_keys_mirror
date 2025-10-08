"""Repository helpers for quiz result persistence."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuizResult

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    from app.quiz.engine import QuizDefinition, QuizResultContext


async def save_result(
    session: AsyncSession,
    user_id: Optional[int],
    definition: "QuizDefinition",
    result: "QuizResultContext",
) -> QuizResult:
    """Persist quiz results with a normalized payload."""

    answers: dict[str, dict[str, object]] = {}
    for question in definition.questions:
        option = result.chosen_options.get(question.id)
        if not option:
            continue
        answers[question.id] = {
            "question": question.text,
            "key": option.key,
            "text": option.text,
            "score": option.score,
            "tags": list(option.tags),
        }

    payload = {
        "quiz": definition.name,
        "title": definition.title,
        "threshold": {
            "label": result.threshold.label,
            "advice": result.threshold.advice,
            "tags": list(result.threshold.tags),
        },
        "answers": answers,
        "collected_tags": list(result.collected_tags),
    }

    entry = QuizResult(
        user_id=int(user_id) if user_id is not None else None,
        quiz=definition.name,
        score=result.total_score,
        level=result.threshold.label or None,
        payload=payload,
    )
    session.add(entry)
    await session.flush()
    return entry


__all__ = ["save_result"]
