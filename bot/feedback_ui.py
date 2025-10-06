"""Telegram UI for collecting human feedback on bot decisions."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from feedback.collector import VoteValue, collector
from feedback.trainer import trainer

router = Router()


def _normalize_vote(raw_vote: str) -> VoteValue | None:
    vote = raw_vote.lower()
    if vote in {"up", "👍", "+", "plus", "1"}:
        return "up"
    if vote in {"down", "👎", "-", "minus", "0"}:
        return "down"
    return None


@router.message(Command("feedback"))
async def feedback_command(message: Message) -> None:
    """Parse `/feedback <id> <up|down>` and store the signal."""

    if not settings.ENABLE_HUMAN_FEEDBACK:
        await message.answer("Сбор обратной связи отключён администратором.")
        return

    text = message.text or ""
    parts = text.split()
    if len(parts) < 3:
        await message.answer(
            "Формат: /feedback <id> <up|down>. Например: /feedback plan123 up"
        )
        return

    _, item_id, vote_raw = parts[:3]
    vote = _normalize_vote(vote_raw)
    if vote is None:
        await message.answer("Используй up или down (можно 👍/👎).")
        return

    collector.record(
        item_id=item_id,
        vote=vote,
        user_id=message.from_user.id if message.from_user else None,
        payload={
            "chat_id": message.chat.id,
            "message_id": message.message_id,
        },
    )
    trainer.update()

    summary = collector.get_item_summary(item_id)
    gain = trainer.quality_gain()
    reply = (
        "Спасибо!\n"
        f"{id_display(item_id)} — {summary['up']} 👍 / {summary['down']} 👎\n"
        f"Прогноз роста качества: {gain:+.1%}"
    )
    await message.answer(reply)


def id_display(item_id: str) -> str:
    return item_id.replace("_", " ")
