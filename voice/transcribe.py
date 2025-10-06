"""Асинхронное распознавание речи через OpenAI Audio API."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import httpx

from app.config import settings

logger = logging.getLogger("voice.transcribe")

_CACHE_DIR = Path(settings.VOICE_CACHE_DIR)
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(digest: str) -> Path:
    return _CACHE_DIR / f"{digest}.json"


async def _call_openai(
    audio_bytes: bytes,
    filename: str,
    mime_type: str = "audio/ogg",
) -> str | None:
    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не настроен, голосовое распознавание недоступно")
        return None

    files = {
        "file": (filename, audio_bytes, mime_type),
        "model": (None, settings.VOICE_MODEL),
        "response_format": (None, "json"),
    }
    if settings.VOICE_LANGUAGE:
        files["language"] = (None, settings.VOICE_LANGUAGE)

    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=90.0, base_url=settings.OPENAI_BASE) as client:
            response = await client.post("/audio/transcriptions", files=files, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Ошибка OpenAI STT: %s", exc, exc_info=True)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Сбой OpenAI STT: %s", exc, exc_info=True)
        return None

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("Не удалось разобрать ответ OpenAI STT: %s", exc, exc_info=True)
        return None

    text = (payload.get("text") or "").strip()
    if not text:
        logger.error("OpenAI STT вернул пустой текст")
        return None
    return text


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    mime_type: str = "audio/ogg",
) -> str | None:
    """Распознаёт речь и кеширует результат."""

    digest = hashlib.sha1(audio_bytes).hexdigest()  # noqa: S324 - не для безопасности
    cache_file = _cache_path(digest)
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            text = data.get("text", "").strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось прочитать кеш STT %s: %s", cache_file, exc)

    text = await _call_openai(audio_bytes, filename, mime_type=mime_type)
    if not text:
        return None

    try:
        cache_file.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось сохранить кеш STT %s: %s", cache_file, exc)

    return text


__all__ = ["transcribe_audio"]
