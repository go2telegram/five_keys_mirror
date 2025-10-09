from __future__ import annotations


def format_tip_message(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    return f"💡 {cleaned}"


def format_sleep_journey_message() -> str:
    return (
        "😴 Как спал после теста?\n"
        "Отметь сон в трекере — регулярные записи помогают видеть прогресс."
    )


def format_stress_journey_message() -> str:
    return (
        "🧘 Дыхание 4-7-8 помогает снизить стресс.\n"
        "Вдох на 4, задержка 7, выдох 8 — повтори 4 цикла прямо сейчас."
    )


def format_tip_click_ack() -> str:
    return "Спасибо! Продолжим присылать полезные подсказки."
