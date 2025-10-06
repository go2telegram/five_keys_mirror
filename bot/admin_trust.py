"""Admin helpers for the trust system."""

from __future__ import annotations

from typing import Iterable, Tuple

from app.config import settings
from network.trust import get_trust_distribution, get_trust_metrics


def _render_distribution(rows: Iterable[Tuple[str, float]]) -> str:
    lines = []
    for idx, (agent_id, score) in enumerate(rows, start=1):
        lines.append(f"{idx:>2}. <code>{agent_id}</code> — {score:.3f}")
    if not lines:
        lines.append("Пока нет данных — зафиксируйте взаимодействия с агентами.")
    return "\n".join(lines)


def build_trust_report(limit: int | None = 10) -> str:
    if not settings.ENABLE_TRUST_SYSTEM:
        return "Система доверия выключена (ENABLE_TRUST_SYSTEM=false)."

    distribution = get_trust_distribution()
    if limit is not None:
        distribution = distribution[:limit]
    metrics = get_trust_metrics()
    metrics_text = (
        "\n".join(
            [
                "<b>Метрики</b>",
                f"Средний уровень доверия: {metrics['avg_trust']:.3f}",
                f"Стандартное отклонение: {metrics['trust_deviation']:.3f}",
            ]
        )
        if distribution
        else ""
    )

    header = "<b>Распределение доверия</b>"
    body = _render_distribution(distribution)
    return "\n\n".join(part for part in [header, body, metrics_text] if part)
