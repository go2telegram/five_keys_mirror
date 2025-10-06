"""Rule-based sentiment analysis utilities.

The module provides a minimalistic sentiment analyser that works
offline and is tailored for short chat messages.  It relies on
extensible lexicons of polar words and heuristics for handling
intensifiers and negations.  Results include a normalised polarity
score, a categorical label and auxiliary metadata that can be used to
track the balance of the dialogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Sequence


_NEGATIONS = {
    "не",
    "ни",
    "без",
    "нет",
    "никогда",
    "никак",
}

_POSITIVE_LEXICON = {
    "классно",
    "круто",
    "супер",
    "отлично",
    "спасибо",
    "благодарю",
    "рад",
    "рада",
    "радость",
    "счастлив",
    "счастлива",
    "люблю",
    "нравится",
    "молодец",
    "замечательно",
    "хорошо",
    "здорово",
    "прекрасно",
}

_NEGATIVE_LEXICON = {
    "плохо",
    "ужасно",
    "ненавижу",
    "бесит",
    "раздражает",
    "устал",
    "устала",
    "злость",
    "злюсь",
    "грусть",
    "печально",
    "страшно",
    "боль",
    "болит",
    "кошмар",
    "тревожно",
    "сложно",
    "проблема",
    "негатив",
    "разочарован",
    "разочарована",
}

_INTENSIFIERS = {
    "очень": 1.4,
    "сильно": 1.3,
    "совсем": 1.2,
    "реально": 1.2,
    "прям": 1.1,
    "прямо": 1.1,
}

_DEINTENSIFIERS = {
    "немного": 0.7,
    "слегка": 0.7,
    "чуть": 0.6,
    "чуть-чуть": 0.6,
    "немножко": 0.6,
}


@dataclass(slots=True)
class SentimentResult:
    """Container with the outcome of the sentiment analysis."""

    polarity: float
    label: str
    confidence: float
    signals: Dict[str, float]

    def is_negative(self) -> bool:
        return self.label == "negative"

    def is_positive(self) -> bool:
        return self.label == "positive"

    def is_neutral(self) -> bool:
        return self.label == "neutral"


class SentimentAnalyzer:
    """A lightweight heuristic sentiment analyser."""

    def __init__(self, neutral_margin: float = 0.1) -> None:
        self.neutral_margin = neutral_margin

    @staticmethod
    def _tokenise(text: str) -> Iterable[str]:
        for token in text.lower().replace("!", " ! ").replace("?", " ? ").split():
            yield token.strip('"'"'()[]{}.,:;\n\t")

    def _score_tokens(self, tokens: Sequence[str]) -> float:
        score = 0.0
        last_intensity = 1.0
        for idx, token in enumerate(tokens):
            intensity = last_intensity
            last_intensity = 1.0
            if token in _INTENSIFIERS:
                last_intensity = _INTENSIFIERS[token]
                continue
            if token in _DEINTENSIFIERS:
                last_intensity = _DEINTENSIFIERS[token]
                continue
            is_negated = idx > 0 and tokens[idx - 1] in _NEGATIONS
            if token in _POSITIVE_LEXICON:
                score += (1.0 if not is_negated else -1.0) * intensity
                continue
            if token in _NEGATIVE_LEXICON:
                score -= (1.0 if not is_negated else -1.0) * intensity
                continue
            if token == "!":
                score *= 1.1
                continue
        return score

    def analyse(self, text: str) -> SentimentResult:
        tokens = list(self._tokenise(text))
        if not tokens:
            return SentimentResult(0.0, "neutral", 0.0, {"tokens": 0})
        raw_score = self._score_tokens(tokens)
        normaliser = max(len(tokens), 1)
        polarity = max(min(raw_score / normaliser, 1.0), -1.0)
        label: str
        if polarity > self.neutral_margin:
            label = "positive"
        elif polarity < -self.neutral_margin:
            label = "negative"
        else:
            label = "neutral"
        confidence = min(abs(polarity) * 1.2, 1.0)
        return SentimentResult(
            polarity=polarity,
            label=label,
            confidence=confidence,
            signals={
                "tokens": float(len(tokens)),
                "raw_score": raw_score,
            },
        )


def sentiment_balance(history: Sequence[SentimentResult]) -> float:
    """Compute an aggregate sentiment balance metric.

    The metric is the average polarity across the supplied history and
    is bounded to [-1.0, 1.0].  It can be tracked as part of the bot's
    metrics to understand how balanced the dialogue is over time.
    """

    if not history:
        return 0.0
    total = sum(result.polarity for result in history)
    return max(min(total / len(history), 1.0), -1.0)
