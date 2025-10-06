"""Admin command handlers for external AI interoperability."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from ethics.validator import EthicsViolation, ensure_allowed
from interop.bridge import ExternalAIError, ask_external_ai, get_cached_summary

router = Router()


@router.message(Command("ask_external"))
async def ask_external(message: Message) -> None:
    if message.from_user.id != settings.ADMIN_ID:
        return

    _, _, query = message.text.partition(" ")
    query = query.strip()
    if not query:
        await message.answer("ℹ️ Использование: /ask_external <запрос>")
        return

    try:
        cleaned_query = ensure_allowed(query)
    except EthicsViolation as exc:
        await message.answer(f"🚫 Запрос отклонён: {exc}")
        return

    cached_summary = get_cached_summary(cleaned_query)
    if cached_summary:
        await message.answer(
            "⚡ Этот запрос уже выполнялся. Отправляю краткое резюме из кэша:\n\n"
            f"{cached_summary}"
        )

    try:
        response = await ask_external_ai(cleaned_query)
    except ExternalAIError as exc:
        await message.answer(f"⚠️ Не удалось получить ответ: {exc}")
        return

    text = (
        f"🤝 Ответ от {response.provider.title()}:\n"
        f"{response.content}\n\n"
        f"📝 Кратко: {response.summary}"
    )
    if len(text) > 4000:
        text = text[:3900] + "…"
    await message.answer(text)
