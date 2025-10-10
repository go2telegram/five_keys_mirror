from __future__ import annotations

from app.retention import journeys as journeys_logic, tips as tips_logic


def format_tip_message(text: str) -> str:
    return tips_logic.clean_tip_text(text)


def format_sleep_journey_message() -> str:
    return journeys_logic.format_message(journeys_logic.SLEEP_JOURNEY)


def format_stress_journey_message() -> str:
    return journeys_logic.format_message(journeys_logic.STRESS_JOURNEY)


def format_tip_click_ack() -> str:
    return "Спасибо! Продолжим присылать полезные подсказки."
