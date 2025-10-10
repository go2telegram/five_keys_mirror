"""Scheduler job that posts a daily turnover digest to the admin chat."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.config import settings
from economy import service


def _top_wallets(limit: int = 5) -> str:
    wallets = sorted(service.list_wallets(), key=lambda w: w.balance, reverse=True)
    if not wallets:
        return "нет активных кошельков"

    lines = []
    for idx, wallet in enumerate(wallets[:limit], start=1):
        lines.append(
            f"{idx}. <code>{wallet.user_id}</code> — {wallet.balance} токенов (уровень {wallet.level})"
        )
    return "\n".join(lines)


async def send_daily_economy_report(bot: Bot, *, day: dt.date | None = None) -> None:
    if not settings.ENABLE_GLOBAL_ECONOMY:
        return

    tz = ZoneInfo(settings.TZ)
    summary = service.get_turnover_summary(day, tz=tz)
    metrics = service.get_metrics()

    text = (
        "📈 <b>Экономика за день</b>\n"
        f"Дата: {summary['day']}\n"
        f"Заработано: <b>{summary['earned']}</b>\n"
        f"Потрачено: <b>{summary['spent']}</b>\n"
        f"Переводы: <b>{summary['transfers']}</b>\n"
        f"Чистый итог: <b>{summary['net']}</b>\n\n"
        "ℹ️ Кумулятивные метрики:\n"
        f"• tokens_earned: {metrics.get('tokens_earned', 0)}\n"
        f"• tokens_spent: {metrics.get('tokens_spent', 0)}\n\n"
        "🏆 Топ кошельков:\n"
        f"{_top_wallets()}"
    )

    try:
        await bot.send_message(settings.ADMIN_ID, text)
    except Exception as exc:
        print(f"[economy] failed to send report: {exc}")
