"""Асинхронная задача еженедельного обновления коэффициентов экономики."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.config import settings
from app.storage import get_economy_kpi, set_regulation_state, update_economy_kpi
from economy.regulation import RegulationState, update_regulation


async def run_weekly_regulation(now: dt.datetime | None = None) -> RegulationState:
    """Основная точка входа для APScheduler и ручных прогонов."""

    if not settings.ENABLE_REGULATION_LAYER:
        # Когда слой выключен, фиксируем причину, чтобы /regulation_status честно об этом сообщил.
        disabled_state = RegulationState(
            tax_rate=0.0,
            subsidy_rate=0.0,
            economic_balance=1.0,
            overheating=False,
            underutilized=False,
            notes="Слой регулирования отключён",
            last_updated=now or dt.datetime.now(dt.timezone.utc),
        )
        set_regulation_state(disabled_state.to_dict())
        return disabled_state

    snapshot = get_economy_kpi()
    state = update_regulation(snapshot, now=now)
    set_regulation_state(state.to_dict())
    return state


async def simulate_and_regulate(kpi_overrides: dict[str, Any]) -> RegulationState:
    """Удобный helper для тестов: обновляет KPI и пересчитывает коэффициенты."""

    update_economy_kpi(**kpi_overrides)
    return await run_weekly_regulation(now=dt.datetime.now(dt.timezone.utc))
