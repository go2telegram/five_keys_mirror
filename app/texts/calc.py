"""Calculator-related text helpers.

Currently only provides button labels for shared calculator UI. Specific
calculator flows continue using static strings and will be migrated
incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import gettext


@dataclass(slots=True)
class CalcTexts:
    """Texts for calculator flows."""

    locale: str

    def back(self) -> str:
        return gettext("calc.buttons.back", self.locale)

    def repeat(self) -> str:
        return gettext("calc.buttons.repeat", self.locale)

    def home(self) -> str:
        return gettext("calc.buttons.home", self.locale)

    def premium_cta(self) -> str:
        return gettext("calc.premium_cta", self.locale)


__all__ = ["CalcTexts"]
