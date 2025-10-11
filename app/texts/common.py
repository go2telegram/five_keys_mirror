"""Common text helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import gettext


@dataclass(slots=True)
class CommonTexts:
    """Container for common messages."""

    locale: str

    def welcome(self) -> str:
        return gettext("common.welcome", self.locale)

    def ask_notify(self) -> str:
        return gettext("common.ask_notify", self.locale)

    def notify_on(self) -> str:
        return gettext("common.notify_on", self.locale)

    def notify_off(self) -> str:
        return gettext("common.notify_off", self.locale)

    def registration_prompt(self) -> str:
        return gettext("common.registration.prompt", self.locale)

    def registration_unavailable(self) -> str:
        return gettext("common.registration.unavailable", self.locale)

    def registration_button(self) -> str:
        return gettext("common.registration.button", self.locale)

    def throttle_in_progress(self) -> str:
        return gettext("common.throttle_in_progress", self.locale)

    def premium_welcome(self) -> str:
        return gettext("common.premium_welcome", self.locale)

    def admin_only(self) -> str:
        return gettext("common.admin_only", self.locale)

    def panel_busy(self) -> str:
        return gettext("common.panel_busy", self.locale)

    def version_report(self, branch: str, commit: str, build_time: str) -> str:
        return "\n".join(
            (
                gettext("common.version.header", self.locale),
                gettext("common.version.branch", self.locale, value=branch),
                gettext("common.version.commit", self.locale, value=commit),
                gettext("common.version.build_time", self.locale, value=build_time),
            )
        )


__all__ = ["CommonTexts"]
