"""Bridge module that proxies requests to external AI providers."""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ExternalAIError(RuntimeError):
    """Raised when a provider cannot process the request."""


@dataclass(slots=True)
class ExternalAIResponse:
    provider: str
    content: str
    summary: str
    raw: dict[str, Any] | None = None


_SUMMARY_CACHE: "OrderedDict[str, str]" = OrderedDict()
_SUMMARY_CACHE_LIMIT = 32
DEFAULT_SYSTEM_PROMPT = "Ты помогаешь команде Five Keys. Отвечай по-русски, конкретно и полезно."


def _remember_summary(key: str, summary: str) -> None:
    trimmed_key = key.strip().lower()
    if trimmed_key in _SUMMARY_CACHE:
        _SUMMARY_CACHE.move_to_end(trimmed_key)
    _SUMMARY_CACHE[trimmed_key] = summary
    while len(_SUMMARY_CACHE) > _SUMMARY_CACHE_LIMIT:
        _SUMMARY_CACHE.popitem(last=False)


def get_cached_summary(key: str) -> str | None:
    trimmed_key = key.strip().lower()
    summary = _SUMMARY_CACHE.get(trimmed_key)
    if summary:
        _SUMMARY_CACHE.move_to_end(trimmed_key)
    return summary


async def ask_external_ai(
    prompt: str,
    *,
    provider: str | None = None,
    system_prompt: str | None = None,
) -> ExternalAIResponse:
    if not settings.ENABLE_CROSS_AI_COMM:
        raise ExternalAIError("Cross-AI communication disabled.")

    provider_name = (provider or settings.CROSS_AI_PROVIDER).lower()
    adapter = _PROVIDERS.get(provider_name)
    if not adapter:
        raise ExternalAIError(f"Provider '{provider_name}' is not configured.")

    sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    logger.info("Dispatching external AI request", extra={"provider": provider_name})
    payload = await adapter(prompt, sys_prompt)
    content = payload.get("content") or ""
    if not content:
        raise ExternalAIError("Empty response received from external AI.")

    summary = _summarize_text(content)
    _remember_summary(prompt, summary)
    return ExternalAIResponse(provider=provider_name, content=content, summary=summary, raw=payload.get("raw"))


def _summarize_text(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


async def _call_openai(prompt: str, system_prompt: str) -> dict[str, Any]:
    if not settings.OPENAI_API_KEY:
        raise ExternalAIError("OPENAI_API_KEY is not configured.")

    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=60.0, base_url=settings.OPENAI_BASE) as client:
        response = await client.post("/chat/completions", headers=headers, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("OpenAI request failed")
            raise ExternalAIError(f"OpenAI error: {exc}") from exc

        data = response.json()
        message = data["choices"][0]["message"]["content"].strip()
        return {"content": message, "raw": data}


async def _call_anthropic(prompt: str, system_prompt: str) -> dict[str, Any]:
    if not settings.ANTHROPIC_API_KEY:
        raise ExternalAIError("ANTHROPIC_API_KEY is not configured.")

    base = settings.ANTHROPIC_BASE.rstrip("/") or "https://api.anthropic.com/v1"
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=60.0, base_url=base) as client:
        response = await client.post("/messages", headers=headers, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("Anthropic request failed")
            raise ExternalAIError(f"Anthropic error: {exc}") from exc

        data = response.json()
        if not data.get("content"):
            raise ExternalAIError("Anthropic response payload is empty.")
        text = " ".join(block.get("text", "").strip() for block in data["content"])
        return {"content": text.strip(), "raw": data}


async def _call_gemini(prompt: str, system_prompt: str) -> dict[str, Any]:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ExternalAIError("GEMINI_API_KEY is not configured.")

    base = settings.GEMINI_BASE.rstrip("/") or "https://generativelanguage.googleapis.com/v1"
    url = f"{base}/models/{settings.GEMINI_MODEL}:generateContent?key={api_key}"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_prompt}\n\nЗапрос: {prompt}"},
                ],
            }
        ]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("Gemini request failed")
            raise ExternalAIError(f"Gemini error: {exc}") from exc

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ExternalAIError("Gemini response payload is empty.")
        text = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []))
        return {"content": text.strip(), "raw": data}


_PROVIDERS: dict[str, Callable[[str, str], Awaitable[dict[str, Any]]]] = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
}
