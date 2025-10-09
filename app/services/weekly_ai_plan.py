"""Weekly AI plan scheduler job."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.session import compat_session, session_scope
from app.repo import events as events_repo
from app.repo import subscriptions as subscriptions_repo

log = logging.getLogger("weekly-plan")


@dataclass(slots=True)
class PlanPayload:
    """Result of :func:`build_ai_plan`."""

    text: str
    recommendations: Sequence[str]

    def render(self) -> str:
        if not self.recommendations:
            return self.text
        bullets = "\n".join(f"• {item}" for item in self.recommendations)
        return f"{self.text}\n\nРекомендации недели:\n{bullets}"


async def build_ai_plan(profile: dict | None = None) -> PlanPayload:
    """Create a deterministic-but-friendly weekly plan."""

    profile = profile or {}
    focus = profile.get("focus", "энергии")
    tone = profile.get("tone", "спокойный")
    text = (
        "🧠 Премиум-план на неделю\n"
        f"Фокус: повышение {focus}. Тон: {tone}.\n"
        "Следуй шагам и адаптируй под себя."
    )
    recs = [
        "7–8 часов сна и утренний свет 10 минут",
        "3 прогулки по 30 минут в быстром темпе",
        "Балансированное питание с 20 г белка на приём",
        "2 короткие сессии дыхания 4-7-8",
    ]
    if profile.get("need_short"):
        recs = recs[:3]
    return PlanPayload(text=text, recommendations=recs)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Применить план на неделю", callback_data="ai_plan:apply")],
            [
                InlineKeyboardButton(text="Сделать проще", callback_data="ai_plan:easier"),
                InlineKeyboardButton(text="Сделать жёстче", callback_data="ai_plan:harder"),
            ],
        ]
    )


async def weekly_ai_plan_job(
    bot: Bot,
    profile_provider,
    scope_factory=session_scope,
    plan_builder=build_ai_plan,
) -> None:
    """Send the refreshed plan to all active premium subscribers."""

    async with compat_session(scope_factory) as session:
        active = await subscriptions_repo.active_users(session)
        deliveries: list[tuple[int, PlanPayload]] = []
        for subscription in active:
            profile = await _resolve_profile(profile_provider, subscription.user_id)
            plan = await plan_builder(profile)
            deliveries.append((subscription.user_id, plan))

        for user_id, plan in deliveries:
            text = plan.render()
            try:
                await bot.send_message(user_id, text, reply_markup=_keyboard())
            except Exception:  # pragma: no cover - network errors mocked in tests
                log.warning("weekly plan delivery failed", exc_info=True)
                continue
            await events_repo.log(
                session,
                user_id,
                "ai_plan_sent",
                {"plan_len": len(text), "rec_count": len(plan.recommendations)},
            )
        await session.commit()


async def _resolve_profile(provider, user_id: int) -> dict:
    if provider is None:
        return {}
    if asyncio.iscoroutinefunction(provider):
        return await provider(user_id)
    if hasattr(provider, "__call__"):
        result = provider(user_id)
        if asyncio.iscoroutine(result):
            return await result
        return result
    raise TypeError("profile_provider must be callable or awaitable")
