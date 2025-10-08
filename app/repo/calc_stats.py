"""Utilities for calculator usage statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event


@dataclass(slots=True)
class CalcUsage:
    calc: str
    count: int
    metrics: dict[str, float | None]


@dataclass(slots=True)
class CalcErrorRecord:
    ts: datetime
    calc: str
    step: str | None
    reason: str | None
    raw_input: str | None
    user_id: int | None


_METRIC_FIELDS: dict[str, dict[str, str]] = {
    "water": {"avg_liters": "liters", "avg_glasses": "glasses"},
    "kcal": {"avg_bmr": "base", "avg_tdee": "tdee", "avg_target": "target"},
    "macros": {
        "avg_calories": "calories",
        "avg_protein": "protein",
        "avg_fats": "fats",
        "avg_carbs": "carbs",
    },
    "bmi": {"avg_bmi": "bmi"},
    "msd": {"avg_ideal_weight": "ideal_weight"},
}


async def calc_usage_summary(session: AsyncSession) -> list[CalcUsage]:
    counts_stmt = (
        select(Event.meta["calc"].astext.label("calc"), func.count(Event.id).label("count"))
        .where(Event.name == "calc_finish")
        .group_by(Event.meta["calc"].astext)
    )
    counts_result = await session.execute(counts_stmt)
    counts_map: dict[str, int] = {}
    for row in counts_result:
        key = row.calc or "unknown"
        counts_map[key] = row.count or 0

    usage: list[CalcUsage] = []
    for calc, fields in _METRIC_FIELDS.items():
        labels = [
            func.avg(cast(Event.meta[column].astext, Float)).label(label)
            for label, column in fields.items()
        ]
        stmt = (
            select(func.count(Event.id).label("count"), *labels)
            .where(Event.name == "calc_finish", Event.meta["calc"].astext == calc)
        )
        result = await session.execute(stmt)
        row = result.one()
        count = row.count or 0
        metrics: dict[str, float | None] = {}
        for label in fields:
            value = getattr(row, label, None)
            metrics[label] = float(value) if value is not None else None
        if count:
            usage.append(CalcUsage(calc=calc, count=count, metrics=metrics))
        counts_map.pop(calc, None)

    for calc, count in counts_map.items():
        if count:
            usage.append(CalcUsage(calc=calc, count=count, metrics={}))

    usage.sort(key=lambda item: item.count, reverse=True)
    return usage


async def calc_errors(session: AsyncSession, limit: int = 5) -> list[CalcErrorRecord]:
    stmt = (
        select(Event)
        .where(Event.name == "calc_error")
        .order_by(Event.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    events = list(result.scalars())
    records: list[CalcErrorRecord] = []
    for event in events:
        meta: dict[str, Any] = event.meta or {}
        records.append(
            CalcErrorRecord(
                ts=event.ts,
                calc=str(meta.get("calc", "unknown")),
                step=meta.get("step"),
                reason=meta.get("reason"),
                raw_input=meta.get("input"),
                user_id=event.user_id,
            )
        )
    return records


__all__ = ["CalcUsage", "CalcErrorRecord", "calc_errors", "calc_usage_summary"]
