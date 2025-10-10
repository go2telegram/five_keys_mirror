"""Quiz-related text helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import gettext


@dataclass(slots=True)
class QuizTexts:
    """Texts used by quiz handlers."""

    locale: str

    def no_quizzes(self) -> str:
        return gettext("quiz.no_quizzes", self.locale)

    def not_found(self) -> str:
        return gettext("quiz.not_found", self.locale)

    def timeout(self) -> str:
        return gettext("quiz.timeout", self.locale)

    def enter_name(self) -> str:
        return gettext("quiz.enter_name", self.locale)

    def button_unrecognized(self) -> str:
        return gettext("quiz.button_unrecognized", self.locale)


__all__ = ["QuizTexts"]
