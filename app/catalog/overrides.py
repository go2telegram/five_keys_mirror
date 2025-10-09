"""Catalog overlay utilities allowing content team to override metadata."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

CATALOG_DIR = Path(__file__).resolve().parent
CATALOG_OVERRIDES_PATH = CATALOG_DIR / "overrides.json"


class CatalogOverrideError(RuntimeError):
    """Raised when overrides.json cannot be parsed."""


def load_overrides() -> Dict[str, Dict[str, Any]]:
    """Load overrides keyed by product id.

    The overrides file is optional and is expected to contain a top-level mapping
    where keys correspond to product ids. Each entry may override ``title``,
    ``short``, ``tags`` or ``aliases`` fields of the underlying catalog item.
    """

    if not CATALOG_OVERRIDES_PATH.exists():
        return {}

    try:
        with CATALOG_OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise CatalogOverrideError("overrides.json is not valid JSON") from exc

    if payload is None:
        return {}

    if isinstance(payload, dict):
        raw_items = payload.get("products") or payload
    else:
        raise CatalogOverrideError("overrides.json must contain an object at the top level")

    overrides: Dict[str, Dict[str, Any]] = {}
    for pid, meta in raw_items.items():
        if not isinstance(pid, str) or not pid:
            continue
        if not isinstance(meta, dict):
            continue
        overrides[pid] = deepcopy(meta)
    return overrides


def apply_overrides(product: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides to a single product item and return the result."""

    if not overrides:
        return product

    merged = deepcopy(product)
    for key in ("title", "short", "description", "tags", "aliases"):
        if key in overrides:
            merged[key] = deepcopy(overrides[key])
    return merged
