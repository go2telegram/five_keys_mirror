"""Utilities for resolving catalog image references to Telegram-friendly objects."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from aiogram.types import FSInputFile

LOG = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_DIR.parent


def _iter_candidate_paths(reference: str) -> Iterator[Path]:
    """Yield possible local paths for an image reference."""

    ref = reference.strip()
    if not ref:
        return

    path = Path(ref)
    relative = ref.lstrip("/")
    if path.is_absolute():
        yield path

    variants: list[str] = [relative]
    if relative.startswith("app/"):
        variants.append(relative[4:])
    if relative.startswith("static/"):
        variants.append(relative[len("static/") :])
    if relative.startswith("catalog/"):
        variants.append(relative[len("catalog/") :])

    name = Path(relative).name
    if name:
        variants.extend(
            [
                f"static/images/products/{name}",
                f"catalog/images/products/{name}",
            ]
        )

    seen: set[str] = set()
    for variant in variants:
        if not variant or variant in seen:
            continue
        seen.add(variant)
        rel_path = Path(variant)
        yield _APP_DIR / rel_path
        yield _REPO_ROOT / rel_path


def resolve_media_reference(image: str | None) -> str | FSInputFile | None:
    """Resolve a catalog image reference to a Telegram-ready media source."""

    if not image:
        return None

    normalized = str(image).strip()
    if not normalized:
        return None
    if normalized.startswith("http"):
        return normalized

    for candidate in _iter_candidate_paths(normalized):
        if candidate.exists():
            return FSInputFile(candidate)

    LOG.warning("Missing local image for reference %s", image)
    return None


__all__ = ["resolve_media_reference"]
