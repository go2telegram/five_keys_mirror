"""Utilities for deriving recommendation tags from calculator results."""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional, Set

DEFAULT_TAG_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _normalize_tags(tags: Iterable[str]) -> set[str]:
    cleaned: set[str] = set()
    for raw in tags:
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            cleaned.add(text)
    return cleaned


class DerivedTagStore:
    """Store for tags derived from calculator inputs with TTL support."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TAG_TTL_SECONDS,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = ttl_seconds
        self._now = now or time.time
        self._store: MutableMapping[int, tuple[set[str], float]] = {}

    def _active_tags(self, user_id: int) -> set[str]:
        payload = self._store.get(user_id)
        if not payload:
            return set()
        tags, expires_at = payload
        if expires_at <= self._now():
            self._store.pop(user_id, None)
            return set()
        return set(tags)

    def get(self, user_id: int) -> set[str]:
        """Return active tags for the user (expired entries are purged)."""

        return self._active_tags(user_id)

    def add(self, user_id: int, tags: Iterable[str]) -> set[str]:
        """Merge tags for the user and refresh TTL."""

        cleaned = _normalize_tags(tags)
        if not cleaned:
            return self.get(user_id)
        merged = self._active_tags(user_id)
        merged.update(cleaned)
        self._store[user_id] = (merged, self._now() + self._ttl)
        return set(merged)

    def set(self, user_id: int, tags: Iterable[str]) -> set[str]:
        """Overwrite tags for the user and refresh TTL."""

        cleaned = _normalize_tags(tags)
        if not cleaned:
            self._store.pop(user_id, None)
            return set()
        self._store[user_id] = (cleaned, self._now() + self._ttl)
        return set(cleaned)

    def clear(self, user_id: Optional[int] = None) -> None:
        """Remove cached tags either for a specific user or for everyone."""

        if user_id is None:
            self._store.clear()
        else:
            self._store.pop(user_id, None)


derived_tags_store = DerivedTagStore()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_water_tags(_: Mapping[str, Any]) -> set[str]:
    return {"dehydration", "electrolytes"}


def _derive_nutrition_tags(data: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()

    flags = data.get("flags")
    if isinstance(flags, Mapping):
        if flags.get("protein_low"):
            tags.update({"protein_low", "collagen"})
        if flags.get("sugar_high") or flags.get("sugar_excess"):
            tags.add("sugar_free")

    weight = _to_float(data.get("weight"))
    protein = _to_float(data.get("protein") or data.get("protein_g"))
    if weight and weight > 0 and protein is not None:
        protein_ratio = protein / weight
        if protein_ratio < 1.5:
            tags.update({"protein_low", "collagen"})

    sugar = _to_float(data.get("sugar"))
    carbs = _to_float(data.get("carbs"))
    if weight and weight > 0:
        if sugar is not None:
            if sugar / weight > 1.0:
                tags.add("sugar_free")
        elif carbs is not None and carbs / weight > 3.5:
            tags.add("sugar_free")

    return tags


def _derive_weight_tags(data: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    bmi = _to_float(data.get("bmi"))
    if bmi is not None:
        if bmi < 18.5 or bmi > 25:
            tags.update({"weight_management", "omega3", "sport"})
        return tags

    category_raw = data.get("category")
    if category_raw is not None:
        category = str(category_raw).strip().lower()
        if category and category not in {"норма", "norm", "normal", "ok"}:
            tags.update({"weight_management", "omega3", "sport"})

    fat = _to_float(data.get("fat"))
    if fat is None:
        fat = _to_float(data.get("fat_percent"))
    if fat is not None and (fat < 18 or fat > 32):
        tags.update({"weight_management", "omega3", "sport"})

    return tags


_CALC_MAP = {
    "water": _derive_water_tags,
    "macros": _derive_nutrition_tags,
    "kcal": _derive_nutrition_tags,
    "bmi": _derive_weight_tags,
    "fat": _derive_weight_tags,
    "fat%": _derive_weight_tags,
    "fat_percent": _derive_weight_tags,
    "bodyfat": _derive_weight_tags,
}


def derive_calculator_tags(
    user_id: int,
    result: Mapping[str, Any] | None,
    *,
    store: DerivedTagStore | None = None,
) -> set[str]:
    """Derive recommendation tags from calculator results and persist them."""

    if user_id is None:
        return set()
    store = store or derived_tags_store
    if not result:
        return store.get(user_id)

    calc_name_raw = result.get("calc")
    if calc_name_raw is None:
        return store.get(user_id)
    calc_name = str(calc_name_raw).strip().lower()
    if not calc_name:
        return store.get(user_id)

    derive = _CALC_MAP.get(calc_name)
    if derive is None:
        return store.get(user_id)

    tags = derive(result)
    if not tags:
        return store.get(user_id)

    return store.add(user_id, tags)


__all__ = [
    "DEFAULT_TAG_TTL_SECONDS",
    "DerivedTagStore",
    "derive_calculator_tags",
    "derived_tags_store",
]
