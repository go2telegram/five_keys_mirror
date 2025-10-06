"""Обработчики голосового интерфейса."""

from __future__ import annotations

import logging
from io import BytesIO

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from bot.voice_commands import voice_processor
from voice.transcribe import transcribe_audio

router = Router()
logger = logging.getLogger("voice.handler")


async def _download_audio(message: Message) -> tuple[bytes, str, str] | None:
    file = message.voice or message.audio
    if not file:
        return None

    filename = "voice.ogg"
    mime = "audio/ogg"

    if message.voice:
        filename = f"{file.file_unique_id}.ogg"
        mime = "audio/ogg"
    elif message.audio:
        filename = file.file_name or f"{file.file_unique_id}.mp3"
        mime = file.mime_type or "audio/mpeg"

    buf = BytesIO()
    try:
        await message.bot.download(file, destination=buf)
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось скачать аудио из Telegram: %s", exc, exc_info=True)
        return None
    buf.seek(0)
    return buf.read(), filename, mime


async def _process_voice_message(audio_message: Message, *, respond_to: Message | None = None) -> None:
    target = respond_to or audio_message

    if not settings.ENABLE_VOICE_INTERFACE:
        await target.answer("Голосовой интерфейс отключен. Установите ENABLE_VOICE_INTERFACE=true.")
        return

    data = await _download_audio(audio_message)
    if not data:
        await target.answer("Не получилось получить аудио. Пришлите голосовое сообщение ещё раз.")
        return

    audio_bytes, filename, mime = data
    transcript = await transcribe_audio(audio_bytes, filename, mime_type=mime)
    if not transcript:
        await target.answer("Не удалось распознать речь. Попробуйте сформулировать команду снова.")
        return

    await target.answer(f"Распознано: «{transcript}»")

    executed = await voice_processor.execute(target, transcript)
    if not executed:
        await target.answer(
            "Команда не распознана. Скажите, например: «Меню», «Отчёт», «Ассистент <запрос>»."
        )


@router.message(Command("voice"))
async def voice_entry(message: Message) -> None:
    if message.reply_to_message and (message.reply_to_message.voice or message.reply_to_message.audio):
        await _process_voice_message(message.reply_to_message, respond_to=message)
        return

    if message.voice or message.audio:
        await _process_voice_message(message)
        return

    if not settings.ENABLE_VOICE_INTERFACE:
        await message.answer("Голосовой интерфейс отключен. Установите ENABLE_VOICE_INTERFACE=true.")
        return

    await message.answer(
        "Пришлите голосовое сообщение или аудиофайл ответом на эту команду — я распознаю и выполню голосовую команду."
    )


@router.message(F.voice)
async def plain_voice(message: Message) -> None:
    await _process_voice_message(message)


@router.message(F.audio)
async def plain_audio(message: Message) -> None:
    await _process_voice_message(message)
