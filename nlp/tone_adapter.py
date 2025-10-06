"""Tone adaptation helpers for the assistant."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .sentiment import SentimentResult


class Tone(str, Enum):
    """Supported response tones."""

    CALM = "calm"
    SUPPORTIVE = "supportive"
    BUSINESS = "business"


@dataclass(slots=True)
class ToneProfile:
    """Instructions describing how the bot should speak."""

    tone: Tone
    system_prompt: str
    user_prefix: Optional[str] = None

    def apply(self, base_system_prompt: str, user_message: str) -> Tuple[str, str]:
        system_prompt = f"{base_system_prompt}\n\n{self.system_prompt}".strip()
        if self.user_prefix and not user_message.lower().startswith(self.user_prefix.lower()):
            user_message = f"{self.user_prefix} {user_message}".strip()
        return system_prompt, user_message


class ToneAdapter:
    """Pick a tone based on the sentiment of the user message."""

    def __init__(
        self,
        supportive_threshold: float = 0.25,
        calm_threshold: float = -0.4,
    ) -> None:
        self.supportive_threshold = supportive_threshold
        self.calm_threshold = calm_threshold

    def select_profile(self, sentiment: SentimentResult) -> ToneProfile:
        if sentiment.polarity <= self.calm_threshold:
            return ToneProfile(
                tone=Tone.CALM,
                system_prompt=(
                    "Отвечай мягко, спокойно и уважительно. Помогай снизить напряжение,"
                    " избегай резких формулировок."
                ),
                user_prefix="Спокойный ответ:",
            )
        if sentiment.polarity >= self.supportive_threshold:
            return ToneProfile(
                tone=Tone.SUPPORTIVE,
                system_prompt=(
                    "Отвечай воодушевлённо и поддерживающе. Признавай эмоции собеседника"
                    " и усиливай позитив."
                ),
                user_prefix="Поддерживающий ответ:",
            )
        return ToneProfile(
            tone=Tone.BUSINESS,
            system_prompt=(
                "Сформулируй ответ в деловом, профессиональном стиле. Будь ясным и"
                " структурным, но доброжелательным."
            ),
            user_prefix="Деловой ответ:",
        )

    def adapt(self, base_system_prompt: str, user_message: str, sentiment: SentimentResult) -> Tuple[str, str, ToneProfile]:
        profile = self.select_profile(sentiment)
        system_prompt, user_prompt = profile.apply(base_system_prompt, user_message)
        return system_prompt, user_prompt, profile
