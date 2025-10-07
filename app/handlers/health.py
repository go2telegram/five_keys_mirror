"""Health check command handlers."""

from __future__ import annotations

import inspect
import logging
from typing import Sequence

from aiogram import Router, __version__ as aiogram_version
from aiogram.filters import Command
from aiogram.types import Message

from app import ALLOWED_UPDATES, build_info
from app.config import settings
from app.db.session import session_scope
from app.repo import events as events_repo

router = Router(name="health")
log_health = logging.getLogger("health")


if settings.DEBUG_COMMANDS:

    @router.message(Command("ping"))
    async def ping(message: Message) -> None:
        """Reply with a simple pong marker."""

        log_health.info(
            "PING ok uid=%s uname=%s",
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", None),
        )
        await message.answer("pong \u2705")

    @router.message(Command("doctor"))
    async def doctor(message: Message) -> None:
        """Provide a short diagnostic report in chat."""

        branch = getattr(build_info, "GIT_BRANCH", "unknown")
        commit = getattr(build_info, "GIT_COMMIT", "unknown")
        build_time = getattr(build_info, "BUILD_TIME", "unknown")

        lines = [
            "Doctor report:",
            f"branch: {branch}",
            f"commit: {commit}",
            f"build_time: {build_time}",
            f"aiogram: {aiogram_version}",
            f"allowed_updates: {', '.join(ALLOWED_UPDATES)}",
        ]

        try:
            webhook = await message.bot.get_webhook_info()
            lines.append(f"webhook: {webhook.url or 'none'} (pending={webhook.pending_update_count})")
        except Exception as exc:  # pragma: no cover - network issues during tests
            webhook = None
            log_health.warning("doctor webhook check failed: %s", exc)
            lines.append("webhook: unavailable")

        recent: Sequence[str] = []
        try:
            async with session_scope() as session:
                events_result = events_repo.recent_events(session, limit=3)
                if inspect.isawaitable(events_result):
                    events = await events_result
                else:
                    events = events_result
                recent = [f"{event.ts.isoformat()} {event.name}" for event in events]
        except Exception as exc:  # pragma: no cover - db issues should surface in logs
            log_health.warning("doctor recent events failed: %s", exc, exc_info=True)

        if recent:
            lines.append("recent events:")
            lines.extend(f"- {entry}" for entry in recent)
        else:
            lines.append("recent events: none")

        log_health.info(
            "DOCTOR report uid=%s uname=%s pending=%s",
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", None),
            getattr(webhook, "pending_update_count", None) if webhook else None,
        )

        await message.answer("\n".join(lines))
