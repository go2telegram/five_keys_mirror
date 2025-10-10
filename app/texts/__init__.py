"""High-level accessors for localized bot texts."""

from __future__ import annotations

from dataclasses import dataclass

from app.texts import calc, common, nav, quiz


@dataclass(slots=True)
class Texts:
    """Container with locale-specific text helpers."""

    locale: str

    @property
    def common(self) -> common.CommonTexts:
        return common.CommonTexts(self.locale)

    @property
    def nav(self) -> nav.NavTexts:
        return nav.NavTexts(self.locale)

    @property
    def quiz(self) -> quiz.QuizTexts:
        return quiz.QuizTexts(self.locale)

    @property
    def calc(self) -> calc.CalcTexts:
        return calc.CalcTexts(self.locale)


__all__ = ["Texts"]
