from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.experiments.runtime import get_active_experiments, get_experiment_status

router = Router()


@router.message(Command("experiments"))
async def experiments_dashboard(message: Message):
    if message.from_user.id != settings.ADMIN_ID:
        return

    if not getattr(settings, "EXPERIMENTS_ENABLED", True):
        await message.answer("Эксперименты выключены в конфиге.")
        return

    active = get_active_experiments()
    if not active:
        await message.answer("Активных A/B тестов нет.")
        return

    chunks: list[str] = ["📊 Активные эксперименты:"]
    for experiment in active:
        status = get_experiment_status(experiment)
        chunks.append(
            f"• {experiment.name} ({experiment.key}) — метрика {experiment.metric}"
        )
        for stat in status["stats"]:
            variant = stat["variant"]
            rate_percent = stat["rate"] * 100
            chunks.append(
                "  {code}: {assignments} юзеров / {conversions} успехов"
                " ({rate:.1f}%)".format(
                    code=variant.code,
                    assignments=stat["assignments"],
                    conversions=stat["conversions"],
                    rate=rate_percent,
                )
            )
    await message.answer("\n".join(chunks))
