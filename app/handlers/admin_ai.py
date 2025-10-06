"""Handlers for AI-assisted diagnostic commands."""
from __future__ import annotations

import time
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from assistant import diagnostic_assistant

router = Router()

_last_call_ts: dict[tuple[int, str], float] = {}


def _check_access(message: Message) -> bool:
    return message.from_user and message.from_user.id == settings.ADMIN_ID


def _is_rate_limited(user_id: int, command: str) -> tuple[bool, float]:
    cooldown = getattr(settings, "ADMIN_AI_RATE_LIMIT_SECONDS", 0)
    if cooldown <= 0:
        return False, 0.0
    now = time.monotonic()
    key = (user_id, command)
    last = _last_call_ts.get(key)
    if last and now - last < cooldown:
        return True, cooldown - (now - last)
    _last_call_ts[key] = now
    return False, 0.0


@router.message(Command("doctor_ai"))
async def doctor_ai(message: Message) -> None:
    if not _check_access(message):
        return
    limited, remaining = _is_rate_limited(message.from_user.id, "doctor_ai")
    if limited:
        await message.answer(f"Подожди ещё {remaining:.0f} сек перед следующим запросом.")
        return

    await message.answer(await diagnostic_assistant.doctor_tldr())


@router.message(Command("suggest_fix"))
async def suggest_fix(message: Message) -> None:
    if not _check_access(message):
        return
    limited, remaining = _is_rate_limited(message.from_user.id, "suggest_fix")
    if limited:
        await message.answer(f"Подожди ещё {remaining:.0f} сек перед следующим запросом.")
        return

    await message.answer(await diagnostic_assistant.suggest_fixes())
