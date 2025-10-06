"""UI helpers for the referral dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from growth.bonuses import BonusProfile
from growth.referrals import generate_referral_link

_DEFAULT_CHANNELS = ("organic", "stories", "reels", "newsletter")


@dataclass(slots=True)
class ReferralDashboard:
    text: str
    keyboard: InlineKeyboardMarkup


def _format_stats(stats: dict[str, int]) -> str:
    return (
        f"Уникальных переходов: <b>{stats.get('clicks', 0)}</b>\n"
        f"Регистраций: <b>{stats.get('joins', 0)}</b>\n"
        f"Конверсий: <b>{stats.get('conversions', 0)}</b>"
    )


def build_dashboard(
    *,
    bot_username: str,
    user_id: int,
    stats: dict[str, int],
    bonus: BonusProfile,
    invited: int,
    channel: Optional[str] = None,
    viral_k: float = 0.0,
    channels: Iterable[str] = _DEFAULT_CHANNELS,
) -> ReferralDashboard:
    channel = channel or channels and next(iter(channels)) or "organic"
    link = generate_referral_link(bot_username, ref_code=str(user_id), channel=channel)

    text_lines = [
        "👥 <b>Реферальная ссылка</b>",
        link,
        "",
        _format_stats(stats),
        f"Приглашённых друзей: <b>{invited}</b>",
        "",
        f"Уровень: <b>{bonus.level}</b> — {bonus.points} pts / {bonus.lifetime_points} lifetime",
        f"Анти-фрод: {'⚠️' if bonus.flagged else '✅'}",
        f"Viral K (30d): <b>{viral_k:.2f}</b>",
        "",
        "Выбери канал, чтобы трекать эффективность."
    ]

    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Поделиться", url=link)
    for ch in channels:
        if ch == channel:
            continue
        kb.button(text=f"📈 {ch}", callback_data=f"ref:channel:{ch}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 2, 1)

    return ReferralDashboard(text="\n".join(text_lines), keyboard=kb.as_markup())
