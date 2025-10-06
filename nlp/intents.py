"""Intent classification helpers for routing user messages."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class Intent(str, Enum):
    """Available high level intents."""

    SUPPORT = "support"
    BUY = "buy"
    LEARN = "learn"
    REPORT = "report"
    ADMIN = "admin"


@dataclass(frozen=True)
class IntentMatch:
    """Result of an intent classification."""

    intent: Intent
    score: float
    keywords: tuple[str, ...]


class IntentClassifier:
    """Lightweight keyword driven intent classifier.

    The bot does not run a large language model in production. Instead we
    rely on carefully curated keyword lists that cover the commands our
    users typically send (buy, learn more, request support, etc.). The
    classifier returns both the most likely intent and the keywords that
    triggered the decision so the caller can provide debugging output if
    necessary.
    """

    #: Keyword dictionary that feeds the scoring function.
    DEFAULT_KEYWORDS: Mapping[Intent, tuple[str, ...]] = {
        Intent.SUPPORT: (
            "консульта", "поддерж", "помог", "связать", "оператор",
            "менедж", "обратн", "help", "support", "вопрос",
        ),
        Intent.BUY: (
            "куп", "заказ", "оплат", "хочу", "оформ", "прайс",
            "стоим", "каталог", "магазин", "buy", "order",
        ),
        Intent.LEARN: (
            "узнать", "расскажи", "что такое", "как", "почему",
            "информац", "learn", "подробнее", "объясни", "курс",
        ),
        Intent.REPORT: (
            "отчет", "отчёт", "pdf", "выгруз", "отправь план",
            "report", "экспорт", "документ", "аналит", "результат",
        ),
        Intent.ADMIN: (
            "admin", "админ", "intents", "интент", "статист",
            "отладк", "debug",
        ),
    }

    def __init__(self, keywords: Mapping[Intent, Iterable[str]] | None = None):
        self._keywords: Mapping[Intent, tuple[str, ...]] = {
            intent: tuple(map(str.lower, words))
            for intent, words in (keywords or self.DEFAULT_KEYWORDS).items()
        }

    def classify(self, text: str) -> IntentMatch:
        """Return the most likely intent for ``text``.

        The scoring function is intentionally simple: we count keyword
        occurrences (substring match) and normalise by the number of
        keywords in the winning intent. If no keywords are matched we fall
        back to ``Intent.LEARN`` because that keeps the user in a
        non-destructive flow where they can browse materials.
        """

        prepared = (text or "").lower()
        scores: dict[Intent, tuple[float, tuple[str, ...]]] = {}

        for intent, keywords in self._keywords.items():
            matched = tuple(kw for kw in keywords if kw in prepared)
            if not matched:
                continue
            # score is normalised so intents with longer keyword lists do
            # not dominate purely due to size.
            score = len(matched) / len(keywords)
            scores[intent] = (score, matched)

        if not scores:
            return IntentMatch(Intent.LEARN, 0.0, tuple())

        intent, (score, matched) = max(
            scores.items(), key=lambda item: (item[1][0], item[0].value)
        )
        return IntentMatch(intent, score, matched)


class IntentStatistics:
    """Simple helper to keep track of classification counts."""

    def __init__(self) -> None:
        self._counter: Counter[Intent] = Counter()

    def add(self, intent: Intent) -> None:
        self._counter[intent] += 1

    def total(self) -> int:
        return sum(self._counter.values())

    def most_common(self, limit: int = 5) -> list[tuple[Intent, int]]:
        return self._counter.most_common(limit)

    def clear(self) -> None:
        self._counter.clear()
