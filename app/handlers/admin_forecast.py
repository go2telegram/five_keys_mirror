"""Handlers for admin forecast commands."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.config import settings
from analytics.forecast import ForecastError, SUPPORTED_METRICS, build_forecast, format_metric_name

router = Router()


@router.message(Command("forecast"))
async def forecast_command(message: Message) -> None:
    """Render forecast for a metric and send it to the admin."""
    if not getattr(settings, "ENABLE_PREDICTIVE_PLANNER", True):
        return
    if message.from_user.id != settings.ADMIN_ID:
        return

    args = message.text.split(maxsplit=1) if message.text else []
    metric = args[1].strip().lower() if len(args) > 1 else "revenue_total"

    try:
        result = await _build_forecast_async(metric)
    except ForecastError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    caption = result.summary
    try:
        await message.answer_photo(
            BufferedInputFile(result.chart_bytes, filename=f"forecast_{metric}.png"),
            caption=caption,
        )
    except Exception:
        await message.answer(caption)


async def _build_forecast_async(metric: str):
    loop = None
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop and loop.is_running():
        import functools

        return await loop.run_in_executor(
            None, functools.partial(build_forecast, metric, 7)
        )
    return build_forecast(metric, 7)


@router.message(Command("forecast_help"))
async def forecast_help(message: Message) -> None:
    if message.from_user.id != settings.ADMIN_ID:
        return
    metrics = "\n".join(f"• {key} — {format_metric_name(key)}" for key in SUPPORTED_METRICS)
    await message.answer(
        "Команда /forecast <metric> строит прогноз на 7 дней.\n\n"
        "Доступные метрики:\n"
        f"{metrics}"
    )
