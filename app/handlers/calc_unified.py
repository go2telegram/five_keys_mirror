"""Utilities for persisting calculator results in a unified format."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.repo import calculators as calculators_repo


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


async def save_result(
    session: AsyncSession,
    user_id: int,
    kind: str,
    payload: Mapping[str, Any] | None,
) -> None:
    normalized = _normalize_value(dict(payload or {}))
    await calculators_repo.save(session, user_id=user_id, kind=kind, payload=normalized)


__all__ = ["save_result"]
