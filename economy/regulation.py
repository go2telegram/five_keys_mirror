"""Регулятор экономики бота.

Модуль концентрирует логику вычисления налогов и субсидий в ответ на KPI
сообщества. Точки входа:
- :func:`update_regulation` — принимает снимок KPI и возвращает новое состояние.
- :func:`get_regulation_state` — выдаёт последнее рассчитанное состояние.

Расчёты намеренно прозрачные: коэффициенты ограничены небольшими значениями,
чтобы в симуляциях легко было добиться устойчивого баланса. Экономический
баланс выражается числом от 0 до 1, где 1 — идеальный режим.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(slots=True)
class RegulationState:
    """Сводная информация по регулированию экономики."""

    tax_rate: float
    subsidy_rate: float
    economic_balance: float
    overheating: bool
    underutilized: bool
    notes: str
    last_updated: dt.datetime

    def to_dict(self) -> dict[str, object]:
        """Удобный helper для сохранения состояния в хранилище."""

        data = asdict(self)
        # datetime as ISO for внешних потребителей
        data["last_updated"] = self.last_updated.isoformat()
        return data


_DEFAULT_STATE = RegulationState(
    tax_rate=0.0,
    subsidy_rate=0.0,
    economic_balance=1.0,
    overheating=False,
    underutilized=False,
    notes="Регулятор ещё не запускался",
    last_updated=dt.datetime.fromtimestamp(0, tz=dt.timezone.utc),
)

_state = _DEFAULT_STATE


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _metric(kpi: Mapping[str, float], key: str, default: float) -> float:
    try:
        value = float(kpi.get(key, default))
    except (TypeError, ValueError):
        value = default
    return value


def calculate_state(kpi: Mapping[str, float], now: dt.datetime | None = None) -> RegulationState:
    """Высчитываем коэффициенты регулирования для заданного снимка KPI."""

    now = now or dt.datetime.now(tz=dt.timezone.utc)

    target_tokens = max(_metric(kpi, "target_tokens", 1_000.0), 1.0)
    circulating = max(_metric(kpi, "circulating_tokens", target_tokens), 0.0)
    velocity = max(_metric(kpi, "velocity", 1.0), 0.0)
    stability_index = _clamp(_metric(kpi, "stability_index", 0.7), 0.0, 1.0)
    utilization = _clamp(_metric(kpi, "utilization", 0.6), 0.0, 1.0)
    engagement = _clamp(_metric(kpi, "engagement_index", 0.75), 0.0, 1.2)

    supply_gap = (circulating - target_tokens) / target_tokens

    overheating = supply_gap > 0.05
    underutilized = supply_gap < -0.05

    # Налог активнее растёт при перегреве и ускорении оборота
    tax_pressure = max(0.0, supply_gap) * 0.18
    tax_pressure += max(0.0, velocity - 1.2) * 0.05
    tax_pressure += max(0.0, 0.8 - utilization) * 0.08
    tax_rate = _clamp(tax_pressure, 0.0, 0.35)

    # Субсидии стимулируют, когда токенов мало или падает вовлечённость
    subsidy_push = max(0.0, -supply_gap) * 0.15
    subsidy_push += max(0.0, 0.9 - engagement) * 0.06
    subsidy_push += max(0.0, 0.5 - utilization) * 0.08
    subsidy_rate = _clamp(subsidy_push, 0.0, 0.25)

    imbalance_penalty = abs(supply_gap) * 0.5
    imbalance_penalty += max(0.0, 1.0 - stability_index) * 0.3
    imbalance_penalty += max(0.0, 0.7 - utilization) * 0.2
    economic_balance = _clamp(1.0 - imbalance_penalty, 0.0, 1.0)

    if overheating:
        note = "Перегрев: задействован налог на оборот"
    elif underutilized:
        note = "Недогрев: активированы субсидии"
    else:
        note = "Баланс в пределах нормы"

    return RegulationState(
        tax_rate=round(tax_rate, 4),
        subsidy_rate=round(subsidy_rate, 4),
        economic_balance=round(economic_balance, 4),
        overheating=overheating,
        underutilized=underutilized,
        notes=note,
        last_updated=now,
    )


def update_regulation(kpi: Mapping[str, float], now: dt.datetime | None = None) -> RegulationState:
    """Пересчёт коэффициентов и сохранение состояния в модуле."""

    global _state
    _state = calculate_state(kpi, now=now)
    return _state


def get_regulation_state() -> RegulationState:
    """Текущее состояние регулятора (без копии)."""

    return _state
