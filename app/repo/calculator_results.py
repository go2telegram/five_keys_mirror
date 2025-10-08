"""Storage helpers for calculator run results and errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalculatorResult


def _normalize_mapping(data: Mapping[str, Any] | Sequence[tuple[str, Any]] | None) -> dict[str, Any]:
    if not data:
        return {}
    if isinstance(data, dict):
        return dict(data)
    return {str(key): value for key, value in data}


def _normalize_tags(tags: Sequence[str] | None) -> list[str]:
    if not tags:
        return []
    normalized: list[str] = []
    for tag in tags:
        if not tag:
            continue
        normalized.append(str(tag))
    return normalized


async def log_success(
    session: AsyncSession,
    user_id: int | None,
    calculator: str,
    *,
    input_data: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    result_data: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    tags: Sequence[str] | None = None,
) -> CalculatorResult:
    record = CalculatorResult(
        user_id=user_id,
        calculator=str(calculator),
        status="ok",
        input_data=_normalize_mapping(input_data),
        result_data=_normalize_mapping(result_data),
        tags=_normalize_tags(tags),
    )
    session.add(record)
    await session.flush()
    return record


async def log_error(
    session: AsyncSession,
    user_id: int | None,
    calculator: str,
    *,
    step: str | None = None,
    raw_value: str | None = None,
    error: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> CalculatorResult:
    payload = dict(extra or {})
    if step:
        payload.setdefault("step", step)
    if raw_value is not None:
        payload.setdefault("raw", raw_value)

    record = CalculatorResult(
        user_id=user_id,
        calculator=str(calculator),
        status="error",
        input_data=payload,
        result_data={},
        tags=[],
        error=(str(error)[:255] if error else None),
    )
    session.add(record)
    await session.flush()
    return record


@dataclass(slots=True)
class UsageStats:
    calculator: str
    ok: int
    error: int


async def usage_summary(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[UsageStats]:
    stmt: Select = select(
        CalculatorResult.calculator,
        CalculatorResult.status,
        func.count(CalculatorResult.id),
    ).group_by(CalculatorResult.calculator, CalculatorResult.status)

    if since is not None:
        stmt = stmt.where(CalculatorResult.created >= since)
    if until is not None:
        stmt = stmt.where(CalculatorResult.created < until)

    stmt = stmt.order_by(CalculatorResult.calculator, CalculatorResult.status)

    result = await session.execute(stmt)
    counters: dict[str, UsageStats] = {}
    for calculator, status, count in result.all():
        stats = counters.setdefault(calculator, UsageStats(calculator=calculator, ok=0, error=0))
        if status == "error":
            stats.error += int(count)
        else:
            stats.ok += int(count)
    return list(counters.values())


async def recent_errors(
    session: AsyncSession,
    *,
    limit: int = 5,
    since: datetime | None = None,
) -> list[CalculatorResult]:
    stmt = (
        select(CalculatorResult)
        .where(CalculatorResult.status == "error")
        .order_by(CalculatorResult.created.desc(), CalculatorResult.id.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(CalculatorResult.created >= since)

    result = await session.execute(stmt)
    return list(result.scalars())


__all__ = [
    "UsageStats",
    "log_error",
    "log_success",
    "recent_errors",
    "usage_summary",
]
