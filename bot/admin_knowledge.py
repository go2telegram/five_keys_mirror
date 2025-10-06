from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime

from app.config import settings
from knowledge.utils import get_event, list_events, upsert_event

router = Router()


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        return value


@router.message(Command("why"))
async def explain_decision(message: Message) -> None:
    if not settings.ENABLE_KNOWLEDGE_CENTER:
        await message.answer("Центр знаний временно отключён.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Использование: /why <event>")
        return

    event = parts[1].strip()
    entry = get_event(event)
    if not entry:
        await message.answer(
            "Не нашёл событие <b>{}</b>. Используйте /why_events, чтобы посмотреть список.".format(event)
        )
        return

    actions = entry.get("actions") or []
    if actions:
        actions_text = "\n".join(f"• {item}" for item in actions)
    else:
        actions_text = "—"

    updated = entry.get("timestamp") or ""
    await message.answer(
        "📚 Причина для <b>{event}</b>\n"
        "{reason}\n\n"
        "🛠 Действия:\n"
        "{actions}\n\n"
        "⏱ Обновлено: {updated}".format(
            event=entry.get("event", event),
            reason=entry.get("reason", "Причина не указана."),
            actions=actions_text,
            updated=_format_timestamp(updated) if updated else "—",
        )
    )


@router.message(Command("why_events"))
async def list_known_events(message: Message) -> None:
    if not settings.ENABLE_KNOWLEDGE_CENTER:
        await message.answer("Центр знаний временно отключён.")
        return

    events = list_events()
    if not events:
        await message.answer("Событий пока нет.")
        return

    formatted = "\n".join(f"• {event}" for event in events)
    await message.answer("📂 Доступные события:\n" + formatted)


@router.message(Command("setwhy"))
async def upsert_reason(message: Message) -> None:
    if message.from_user.id != settings.ADMIN_ID:
        return

    payload = message.text.split(maxsplit=1)
    if len(payload) < 2:
        await message.answer(
            "Использование: /setwhy <event> | <reason> | <действие 1>; <действие 2>"
        )
        return

    data = [chunk.strip() for chunk in payload[1].split("|")]
    if len(data) < 2:
        await message.answer(
            "Нужно минимум два блока: событие и причина. Формат: /setwhy event | причина | действие1; действие2"
        )
        return

    event = data[0]
    reason = data[1]
    actions = []
    if len(data) > 2:
        actions = [part.strip() for part in data[2].split(";") if part.strip()]

    try:
        entry = upsert_event(
            event=event,
            reason=reason,
            actions=actions,
            actor=str(message.from_user.id),
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "Обновлено событие <b>{event}</b>. Время: {ts}".format(
            event=entry["event"],
            ts=_format_timestamp(entry.get("timestamp", "")),
        )
    )
