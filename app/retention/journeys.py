"""Retention follow-up journeys after quizzes."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from aiogram.utils.keyboard import InlineKeyboardBuilder

SLEEP_JOURNEY = "sleep_checkin"
STRESS_JOURNEY = "stress_relief"

SLEEP_CTA_CALLBACK = "journey:tracker_sleep"
STRESS_CTA_CALLBACK = "journey:premium_plan"

JOURNEY_DELAYS: dict[str, dt.timedelta] = {
    SLEEP_JOURNEY: dt.timedelta(hours=24),
    STRESS_JOURNEY: dt.timedelta(hours=48),
}

JOURNEY_CTA_EVENTS: dict[str, str] = {
    SLEEP_JOURNEY: "journey_sleep_cta",
    STRESS_JOURNEY: "journey_premium_cta",
}

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from aiogram.types import InlineKeyboardMarkup


def format_message(journey: str) -> str:
    if journey == SLEEP_JOURNEY:
        return (
            "😴 Как спал после теста?\n"
            "Отметь сон в трекере — регулярные записи помогают видеть прогресс."
        )
    if journey == STRESS_JOURNEY:
        return (
            "🧘 Готов вернуться к дыханию 4-7-8?\n"
            "Это простой способ снизить стресс за пару минут."
        )
    return ""


def format_cta_reply(journey: str) -> str:
    if journey == SLEEP_JOURNEY:
        return "Чтобы отслеживать сон, используй команду <code>/track_sleep 7</code> или поделись фактическими часами."
    if journey == STRESS_JOURNEY:
        return "💎 Премиум даёт еженедельные планы, трекеры и поддержку. Оформить подписку можно в разделе /premium."
    return ""


def keyboard(journey: str) -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    if journey == SLEEP_JOURNEY:
        builder.button(text="📲 Включить трекер сна", callback_data=SLEEP_CTA_CALLBACK)
    elif journey == STRESS_JOURNEY:
        builder.button(text="💡 Хочу Премиум-план", callback_data=STRESS_CTA_CALLBACK)
    return builder.as_markup()
