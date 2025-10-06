"""Daily forecast job for the predictive planner."""
from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.config import settings
from analytics.forecast import ForecastError, SUPPORTED_METRICS, build_forecast


async def send_daily_forecasts(bot: Bot) -> None:
    """Build forecasts for configured metrics and push them to the admin chat."""
    if not getattr(settings, "ENABLE_PREDICTIVE_PLANNER", True):
        return

    metrics = _parse_metrics(getattr(settings, "FORECAST_METRICS", ""))
    horizon = getattr(settings, "FORECAST_DAYS", 7)

    for metric in metrics:
        try:
            result = await asyncio.to_thread(build_forecast, metric, horizon)
        except ForecastError as exc:
            await _notify(bot, f"⚠️ Прогноз по {metric} не построен: {exc}")
            continue
        except Exception as exc:  # unexpected
            await _notify(bot, f"⚠️ Сбой прогноза по {metric}: {exc}")
            continue

        caption = result.summary
        try:
            await bot.send_photo(
                settings.ADMIN_ID,
                BufferedInputFile(result.chart_bytes, filename=f"forecast_{metric}.png"),
                caption=caption,
            )
        except Exception:
            await _notify(bot, caption)


async def _notify(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(settings.ADMIN_ID, text)
    except Exception:
        pass


def _parse_metrics(csv: str) -> list[str]:
    if not csv:
        return list(SUPPORTED_METRICS.keys())
    out = []
    for part in csv.split(","):
        key = part.strip().lower()
        if key:
            out.append(key)
    return out or list(SUPPORTED_METRICS.keys())
