from __future__ import annotations


def format_tip_message(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    return f"💡 {cleaned}"


def format_sleep_journey_message() -> str:
    return "🌙 Как прошёл твой сон? Выбери, как ближе к правде."


def format_stress_journey_message() -> str:
    return "😌 Как сейчас уровень стресса?"


def format_tip_click_ack() -> str:
    return "Спасибо! Продолжим присылать полезные подсказки."
