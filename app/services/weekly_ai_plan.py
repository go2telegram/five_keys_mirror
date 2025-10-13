"""Weekly AI plan scheduler job."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Sequence

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db.session import compat_session, session_scope
from app.repo import (
    events as events_repo,
    profiles as profiles_repo,
    subscriptions as subscriptions_repo,
)
from app.services import premium_metrics
from app.services.plan_storage import archive_plan

log = logging.getLogger("weekly-plan")


@dataclass(slots=True)
class PlanPayload:
    """Result of :func:`build_ai_plan`."""

    text: str
    recommendations: Sequence[str]
    plan_json: dict[str, Any] | None = None

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
    goals = list(profile.get("goals", []))
    text = f"🧠 Премиум-план на неделю\nФокус: повышение {focus}. Тон: {tone}.\nСледуй шагам и адаптируй под себя."
    recs = [
        "7–8 часов сна и утренний свет 10 минут",
        "3 прогулки по 30 минут в быстром темпе",
        "Балансированное питание с 20 г белка на приём",
        "2 короткие сессии дыхания 4-7-8",
    ]
    if profile.get("need_short"):
        recs = recs[:3]
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    plan_json = {
        "title": "AI-план на неделю",
        "summary": text,
        "recommendations": list(recs),
        "focus": focus,
        "tone": tone,
        "goals": goals,
        "profile": deepcopy(profile),
        "generated_at": generated_at,
        "source": profile.get("source", "auto"),
        "model": getattr(settings, "AI_PLAN_MODEL", "gpt-4o-mini"),
    }
    return PlanPayload(text=text, recommendations=recs, plan_json=plan_json)


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

        premium_metrics.set_active_subs(len(deliveries))

        for user_id, plan in deliveries:
            text = plan.render()
            plan_json = deepcopy(plan.plan_json or {})
            plan_json.setdefault("recommendations", list(plan.recommendations))
            plan_json.setdefault("summary", plan.text)
            plan_json.setdefault("goals", [])
            plan_json["source"] = plan_json.get("source") or "weekly"
            try:
                await bot.send_message(user_id, text, reply_markup=_keyboard())
            except Exception:  # pragma: no cover - network errors mocked in tests
                log.warning("weekly plan delivery failed", exc_info=True)
                continue
            try:
                await profiles_repo.save_plan(session, user_id, plan_json)
            except Exception:
                log.warning("failed to persist plan in profile", exc_info=True)
            try:
                archive_plan(user_id, plan_json)
            except Exception:
                log.warning("failed to archive plan", exc_info=True)
            premium_metrics.record_ai_plan(len(text))
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
    if callable(provider):
        result = provider(user_id)
        if asyncio.iscoroutine(result):
            return await result
        return result
    raise TypeError("profile_provider must be callable or awaitable")
