from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiogram import Bot

from app.config import settings
from app.features import disable_feature
from app.metrics import get_metrics_snapshot
from governor.engine import ActionContext, GovernorEngine

_ROOT = Path(__file__).resolve().parent.parent
_RULES_PATH = _ROOT / "governor" / "rules.yml"
_LOG_PATH = _ROOT / "governor.log"


async def _disable_feature_action(value: Any, context: ActionContext) -> str:
    feature_name = str(value)
    was_enabled = disable_feature(feature_name)
    note = "disabled" if was_enabled else "already_disabled"
    if context.bot and context.admin_chat_id:
        try:
            await context.bot.send_message(
                context.admin_chat_id,
                f"⚠️ Governor: feature '{feature_name}' disabled (rule: {context.rule_condition}).",
            )
        except Exception:
            pass
    return f"feature '{feature_name}' {note}"


async def _alert_action(value: Any, context: ActionContext) -> str:
    text = str(value)
    if context.bot and context.admin_chat_id:
        try:
            await context.bot.send_message(
                context.admin_chat_id,
                f"🚨 Governor alert ({context.rule_condition}): {text}",
            )
        except Exception:
            pass
    return f"alert sent: {text}"


def _build_engine() -> GovernorEngine:
    return GovernorEngine(
        rules_path=_RULES_PATH,
        metrics_provider=get_metrics_snapshot,
        action_handlers={
            "disable_feature": _disable_feature_action,
            "alert": _alert_action,
        },
        log_path=_LOG_PATH,
    )


_engine: GovernorEngine = _build_engine()
_engine_lock: asyncio.Lock | None = None


def _get_engine_lock() -> asyncio.Lock:
    global _engine_lock
    if _engine_lock is None:
        _engine_lock = asyncio.Lock()
    return _engine_lock


def get_engine() -> GovernorEngine:
    return _engine


async def run_governor(bot: Bot) -> None:
    async with _get_engine_lock():
        await _engine.run(bot=bot, admin_chat_id=settings.ADMIN_ID)


__all__ = ["get_engine", "run_governor"]
