"""Helpers for working with UTM parameters and deep links."""

from __future__ import annotations

import shlex
from typing import Mapping
from urllib.parse import parse_qsl, quote_plus, urlencode

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
_SHORT_KEYS = {"source": "utm_source", "medium": "utm_medium", "campaign": "utm_campaign", "content": "utm_content"}


def normalize_utm_key(key: str) -> str | None:
    normalized = key.strip().lower()
    if not normalized:
        return None
    if normalized in UTM_KEYS:
        return normalized
    return _SHORT_KEYS.get(normalized)


def extract_utm_params(payload: str) -> dict[str, str]:
    """Parse ``payload`` and return a mapping of UTM parameters."""

    result: dict[str, str] = {}
    if not payload:
        return result
    for key, value in parse_qsl(payload, keep_blank_values=False):
        utm_key = normalize_utm_key(key)
        if utm_key and value:
            result[utm_key] = value
    return result


def parse_utm_kv(text: str) -> dict[str, str]:
    """Parse key=value pairs from a command argument string."""

    result: dict[str, str] = {}
    if not text:
        return result
    try:
        tokens = shlex.split(text, comments=False, posix=True)
    except ValueError:
        tokens = text.split()
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        utm_key = normalize_utm_key(key)
        cleaned = value.strip()
        if utm_key and cleaned:
            result[utm_key] = cleaned
    return result


def build_deep_link(bot_username: str, params: Mapping[str, str]) -> tuple[str, str]:
    """Return a Telegram deep-link and decoded payload for the provided ``params``."""

    sanitized: dict[str, str] = {}
    for key, value in params.items():
        utm_key = normalize_utm_key(key)
        if utm_key is None:
            continue
        cleaned = value.strip()
        if cleaned:
            sanitized[utm_key] = cleaned
    if not sanitized:
        return f"https://t.me/{bot_username}", ""
    start_payload = urlencode(sanitized)
    encoded = quote_plus(start_payload)
    return f"https://t.me/{bot_username}?start={encoded}", start_payload


def format_utm_label(
    source: str | None,
    medium: str | None,
    campaign: str | None,
    content: str | None,
) -> str:
    """Return a readable label for a UTM tuple."""

    src = source or "organic"
    med = medium or "—"
    extras = [item for item in (campaign, content) if item]
    if extras:
        return f"{src} / {med} · {' · '.join(extras)}"
    return f"{src} / {med}"


def format_utm_tuple(
    source: str | None,
    medium: str | None,
    campaign: str | None,
    content: str | None,
) -> str:
    values = [source or "—", medium or "—", campaign or "—", content or "—"]
    return " | ".join(values)


__all__ = [
    "UTM_KEYS",
    "build_deep_link",
    "extract_utm_params",
    "format_utm_label",
    "format_utm_tuple",
    "normalize_utm_key",
    "parse_utm_kv",
]
