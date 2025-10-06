"""Admin tools for observing the human–machine symbiosis pipeline."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from symbiosis.core import symbiosis_engine

router = Router(name="admin_symbiosis")


def _format_percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


@router.message(Command("symbiosis_status"))
async def symbiosis_status(message: Message) -> None:
    """Send the current collaboration balance to the admin."""

    if not settings.ENABLE_SYMBIOTIC_INTELLIGENCE:
        return

    if message.from_user.id != settings.ADMIN_ID:
        return

    status = await symbiosis_engine.status()

    human = status["human_contribution"]
    machine = status["machine_contribution"]
    balance = status["balance"]
    tone = status["tonal_alignment"]
    mutual = status["mutual_understanding"]
    hmi = status["hmi"]

    text = (
        "🤝 <b>Symbiosis status</b>\n"
        f"Iterations observed: {status['iterations']} (window {status['window_size']})\n"
        f"Human contribution: {_format_percentage(human)}\n"
        f"Machine contribution: {_format_percentage(machine)}\n"
        f"Balance (human share): {_format_percentage(balance)}\n"
        f"Tonal alignment: {_format_percentage(tone)}\n"
        f"Mutual understanding: {_format_percentage(mutual)}\n"
        f"<b>HMI</b>: {_format_percentage(hmi)}"
    )

    await message.answer(text)
