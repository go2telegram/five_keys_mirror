"""Weekly AI plan scheduler integration."""

from __future__ import annotations

import logging

from aiogram import Bot

from app.db.session import compat_session, session_scope
from app.reco.ai_reasoner import build_ai_plan
from app.repo import subscriptions as subscriptions_repo
from app.utils.text import split_md

log = logging.getLogger("weekly-ai-plan")


async def premium_users() -> list[int]:
    """Return IDs of users with an active premium subscription."""

    async with compat_session(session_scope) as session:
        active = await subscriptions_repo.active_users(session)
        return [subscription.user_id for subscription in active if subscription.user_id]


async def weekly_ai_plan_job(bot: Bot) -> None:
    """Send refreshed AI plans to all premium subscribers."""

    users = await premium_users()
    if not users:
        log.info("weekly_ai_plan_job: no active premium users")
        return

    for user_id in users:
        try:
            text = await build_ai_plan(user_id, "7d")
        except Exception:  # pragma: no cover - defensive logging
            log.exception("weekly_ai_plan_job: failed to build plan for user %s", user_id)
            continue

        try:
            await bot.send_message(user_id, "🆕 Твой обновлённый план на неделю готов!")
            for chunk in split_md(text, 3500):
                await bot.send_message(user_id, chunk, parse_mode="Markdown")
        except Exception:  # pragma: no cover - network errors
            log.exception("weekly_ai_plan_job: failed to deliver plan to user %s", user_id)
            continue


__all__ = ["premium_users", "weekly_ai_plan_job"]
