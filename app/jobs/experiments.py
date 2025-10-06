from __future__ import annotations

from aiogram import Bot

from app.config import settings
from app.experiments.runtime import (
    ensure_next_experiment_started,
    evaluate_running_experiments,
    get_active_experiments,
)


async def experiments_cycle(bot: Bot) -> None:
    """Автоматический цикл A/B: запуск, проверка, отчёты."""
    if not getattr(settings, "EXPERIMENTS_ENABLED", True):
        return

    started = ensure_next_experiment_started()
    if started:
        await bot.send_message(
            settings.ADMIN_ID,
            "🚀 Запущен эксперимент «{name}»\n{hypothesis}".format(
                name=started.name,
                hypothesis=started.hypothesis,
            ),
        )

    running = get_active_experiments()
    if not running:
        return

    analyses = evaluate_running_experiments(len(running))
    for result in analyses:
        experiment = result["experiment"]
        winner = result.get("winner")
        lift_rel = result.get("winner_lift", result.get("lift_rel", 0.0))
        p_value = result.get("p_corrected", result.get("p_value", 1.0))
        if winner:
            sign = "+" if lift_rel >= 0 else ""
            message = (
                f"✅ Эксперимент «{experiment.name}» завершён.\n"
                f"{winner.code} {sign}{lift_rel:.0f} %(p = {p_value:.2f})"
            )
        else:
            message = (
                f"⛔ Эксперимент «{experiment.name}» остановлен без победителя.\n"
                f"p = {p_value:.2f}"
            )
        await bot.send_message(settings.ADMIN_ID, message)
