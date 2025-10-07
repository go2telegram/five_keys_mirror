"""Minimal fallback implementation of :mod:`python-slugify` used for offline builds.

This module provides a ``slugify`` function compatible with the public API of
``python-slugify`` that supports the ``lowercase`` and ``language`` arguments we
need.  It focuses on Cyrillic transliteration so the catalog builder can produce
stable identifiers without requiring external dependencies in offline
environments.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

__all__ = ["slugify"]


# Basic transliteration table for Cyrillic characters.
TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _transliterate(value: str) -> str:
    result: list[str] = []
    for char in value:
        lower = char.lower()
        mapped = TRANSLIT_MAP.get(lower)
        if mapped is None:
            result.append(char)
            continue
        if char.isupper():
            mapped = mapped.capitalize()
        result.append(mapped)
    return "".join(result)


def slugify(value: Any, *, lowercase: bool = True, language: str | None = None) -> str:
    """Return a slugified string similar to :func:`python-slugify.slugify`."""

    if value is None:
        value = ""
    text = str(value)
    if language and language.lower() == "ru":
        text = text.replace("Ё", "Е").replace("ё", "е")
    text = _transliterate(text)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    if lowercase:
        ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    ascii_text = re.sub(r"-+", "-", ascii_text).strip("-")
    return ascii_text
