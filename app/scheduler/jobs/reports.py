"""Admin-facing scheduled reports."""
import asyncio

from aiogram import Bot

from app.notifications import (
    collect_daily_stats,
    notify_admins,
    render_error_report,
    render_stats_report,
)


async def send_daily_admin_report(bot: Bot, window_hours: int = 24) -> None:
    """Deliver an aggregated report with recent stats and errors."""
    stats, errors = await asyncio.gather(
        collect_daily_stats(window_hours),
        render_error_report(window_hours=window_hours, limit=5),
    )
    report = render_stats_report(stats)
    message = f"{report}\n\n{errors}"
    await notify_admins(
        message,
        bot=bot,
        silent=True,
        event_kind="daily_report",
        event_payload={"window_hours": window_hours},
    )
