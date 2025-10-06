"""Weekly growth digest sender."""
from __future__ import annotations

from datetime import timedelta

from aiogram import Bot

from app.config import settings
from growth.bonuses import get_digest_snapshot as bonuses_snapshot
from growth.referrals import get_digest_snapshot as referrals_snapshot

_WINDOW = timedelta(days=7)


async def send_growth_digest(bot: Bot) -> None:
    """Compile and deliver the weekly growth digest."""

    stats_ref = referrals_snapshot(window=_WINDOW)
    stats_bonus = bonuses_snapshot(window=_WINDOW)
    viral_k = stats_ref.get("viral_k", 0.0)
    top_channels = sorted(
        stats_ref.get("channels", {}).items(), key=lambda item: item[1], reverse=True
    )
    bonus_channels = sorted(
        stats_bonus.get("channels", {}).items(), key=lambda item: item[1], reverse=True
    )

    lines = [
        "🌱 <b>Growth digest</b>",
        "",
        f"Виральность K: <b>{viral_k:.2f}</b>",
        f"Клики: {stats_ref['clicks']} / Регистрации: {stats_ref['joins']} / Конверсии: {stats_ref['conversions']}",
        "",
        "Топ каналов по лидам:",
    ]
    if top_channels:
        for name, count in top_channels[:5]:
            lines.append(f" • {name}: {count}")
    else:
        lines.append(" • данных ещё нет")

    lines.append("")
    lines.append("Бонусы за неделю:")
    lines.append(
        f" • награждений: {stats_bonus['awards']} | очков: {stats_bonus['points']} | каналов: {len(stats_bonus['channels'])}"
    )
    if bonus_channels:
        lines.append(" • топ по конверсиям:")
        for name, count in bonus_channels[:3]:
            lines.append(f"    - {name}: {count}")

    text = "\n".join(lines)
    try:
        await bot.send_message(settings.ADMIN_ID, text)
    except Exception:  # pragma: no cover - avoid breaking scheduler on network errors
        pass
