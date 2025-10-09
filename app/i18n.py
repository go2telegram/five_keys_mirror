"""Minimal i18n layer backed by YAML dictionaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

LOCALES_ROOT = Path(__file__).resolve().parent / "locales"
DEFAULT_LOCALE = "ru"

_CACHE: dict[str, Mapping[str, Any]] = {}


class LocaleError(RuntimeError):
    """Raised when locale files cannot be parsed."""


def available_locales() -> set[str]:
    """Return a set of available locale codes."""

    locales: set[str] = set()
    for path in LOCALES_ROOT.glob("*.yaml"):
        locales.add(path.stem)
    return locales


def _load_locale(code: str) -> Mapping[str, Any]:
    if code in _CACHE:
        return _CACHE[code]
    path = LOCALES_ROOT / f"{code}.yaml"
    if not path.exists():
        raise LocaleError(f"Locale file missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, Mapping):
        raise LocaleError(f"Locale {code} must contain a mapping")
    _CACHE[code] = data
    return data


def clear_cache() -> None:
    _CACHE.clear()


def resolve_locale(language_code: str | None) -> str:
    """Resolve the best locale for provided Telegram language code."""

    if not language_code:
        return DEFAULT_LOCALE
    normalized = language_code.split("-")[0].lower()
    if normalized in available_locales():
        return normalized
    return DEFAULT_LOCALE


def gettext(key: str, locale: str, *, fallback: str | None = DEFAULT_LOCALE, **params: Any) -> str:
    """Retrieve a translation for ``key`` in ``locale`` with optional fallback."""

    locales = [locale]
    if fallback and fallback not in locales:
        locales.append(fallback)

    for code in locales:
        try:
            root = _load_locale(code)
        except LocaleError:
            continue
        value = _lookup(key, root)
        if value is not None:
            return value.format(**params)
    return key


def _lookup(key: str, data: Mapping[str, Any]) -> str | None:
    parts = [part for part in key.split(".") if part]
    cursor: Any = data
    for part in parts:
        if isinstance(cursor, Mapping) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    if isinstance(cursor, str):
        return cursor
    return None
