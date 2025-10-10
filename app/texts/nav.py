"""Navigation and onboarding texts."""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import gettext


@dataclass(slots=True)
class NavTexts:
    """Texts used in navigation flows."""

    locale: str

    def greeting_classic(self) -> str:
        return gettext("nav.greeting.classic", self.locale)

    def greeting_fresh(self) -> str:
        return gettext("nav.greeting.fresh", self.locale)

    def onboarding_confirmation_classic(self) -> str:
        return gettext("nav.onboarding.confirmation.classic", self.locale)

    def onboarding_confirmation_fresh(self) -> str:
        return gettext("nav.onboarding.confirmation.fresh", self.locale)

    def returning_prompt_classic(self) -> str:
        return gettext("nav.returning_prompt.classic", self.locale)

    def returning_prompt_fresh(self) -> str:
        return gettext("nav.returning_prompt.fresh", self.locale)

    def recommend_goal_prompt(self) -> str:
        return gettext("nav.recommend.goal_prompt", self.locale)

    def menu_tests(self) -> str:
        return gettext("nav.menu.tests", self.locale)

    def menu_premium(self) -> str:
        return gettext("nav.menu.premium", self.locale)

    def menu_help(self) -> str:
        return gettext("nav.menu.help", self.locale)

    def admin_panel_help(self) -> str:
        return gettext("nav.admin.panel_help", self.locale)


__all__ = ["NavTexts"]
