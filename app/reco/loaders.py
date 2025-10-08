"""Loaders for recommendation ontology and product rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import AudienceBoost, FreshnessConfig, MatchConfig, ProductRule, TagDefinition

DATA_ROOT = Path(__file__).resolve().parent

_ALLOWED_UTM_CATEGORIES = {
    "energy",
    "sleep",
    "stress",
    "immunity",
    "gut",
    "metabolism",
    "beauty",
    "lifestyle",
    "snacks",
    "focus",
}


class RecommendationConfigError(RuntimeError):
    """Raised when recommendation YAML files contain invalid data."""


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise RecommendationConfigError(f"Configuration file not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - yaml library provides details
        raise RecommendationConfigError(f"Failed to parse YAML: {path}") from exc


def load_tag_ontology() -> dict[str, TagDefinition]:
    payload = _load_yaml(DATA_ROOT / "tag_ontology.yaml")
    tags_raw = payload.get("tags") if isinstance(payload, dict) else None
    if not isinstance(tags_raw, dict) or not tags_raw:
        raise RecommendationConfigError("tag_ontology.yaml must contain a non-empty 'tags' mapping")

    result: dict[str, TagDefinition] = {}
    for key, data in tags_raw.items():
        if not isinstance(key, str) or not key.strip():
            raise RecommendationConfigError("Tag keys must be non-empty strings")
        key_norm = key.strip()
        if not isinstance(data, dict):
            raise RecommendationConfigError(f"Tag '{key_norm}' must be an object")
        title = str(data.get("title") or key_norm).strip()
        description = str(data.get("description") or "").strip()
        group = str(data.get("group") or "general").strip()
        sources_raw = data.get("sources") or []
        implies_raw = data.get("implies") or []
        sources: list[str] = []
        implies: list[str] = []
        if isinstance(sources_raw, Iterable) and not isinstance(sources_raw, (str, bytes)):
            for src in sources_raw:
                if not src:
                    continue
                sources.append(str(src))
        elif isinstance(sources_raw, (str, bytes)) and sources_raw:
            sources.append(str(sources_raw))
        if isinstance(implies_raw, Iterable) and not isinstance(implies_raw, (str, bytes)):
            for dep in implies_raw:
                if not dep:
                    continue
                implies.append(str(dep))
        elif isinstance(implies_raw, (str, bytes)) and implies_raw:
            implies.append(str(implies_raw))
        sources_clean = sorted({src.strip() for src in sources if str(src).strip()})
        implies_clean = sorted({dep.strip() for dep in implies if str(dep).strip()})
        result[key_norm] = TagDefinition(
            key=key_norm,
            title=title,
            description=description,
            group=group,
            sources=tuple(sources_clean),
            implies=tuple(implies_clean),
        )
    return result


def _parse_match(raw: Any) -> MatchConfig:
    if not isinstance(raw, dict):
        raise RecommendationConfigError("Each product rule must define a 'match' object")
    tags_raw = raw.get("tags")
    if not isinstance(tags_raw, dict) or not tags_raw:
        raise RecommendationConfigError("'match.tags' must be a non-empty mapping")
    weights: dict[str, float] = {}
    for tag, weight in tags_raw.items():
        if not isinstance(tag, str) or not tag.strip():
            raise RecommendationConfigError("Tag names inside 'match.tags' must be strings")
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            raise RecommendationConfigError(f"Weight for tag '{tag}' must be numeric")
        if weight_value <= 0:
            raise RecommendationConfigError(f"Weight for tag '{tag}' must be positive")
        weights[tag.strip()] = weight_value
    threshold = raw.get("threshold", 0.0)
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        raise RecommendationConfigError("match.threshold must be numeric")
    if threshold_value < 0 or threshold_value > 1:
        raise RecommendationConfigError("match.threshold must be between 0 and 1")
    return MatchConfig(weights=weights, threshold=threshold_value)


def _parse_audience(raw: Any) -> tuple[AudienceBoost, ...]:
    if not raw:
        return ()
    if not isinstance(raw, Iterable):
        raise RecommendationConfigError("audience must be a list of boost objects")
    boosts: list[AudienceBoost] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RecommendationConfigError("audience entries must be objects")
        factor_raw = entry.get("factor", 1.0)
        try:
            factor = float(factor_raw)
        except (TypeError, ValueError):
            raise RecommendationConfigError("audience.factor must be numeric")
        if factor <= 0:
            raise RecommendationConfigError("audience.factor must be positive")
        any_of_raw = entry.get("any") or []
        all_of_raw = entry.get("all") or []
        any_of = frozenset(str(item).strip() for item in any_of_raw if item)
        all_of = frozenset(str(item).strip() for item in all_of_raw if item)
        label = entry.get("label")
        boosts.append(AudienceBoost(factor=factor, any_of=any_of, all_of=all_of, label=str(label).strip() if label else None))
    return tuple(boosts)


def _parse_freshness(raw: Any) -> FreshnessConfig:
    if raw is None:
        return FreshnessConfig()
    if not isinstance(raw, dict):
        raise RecommendationConfigError("freshness must be an object")
    base = raw.get("base", 1.0)
    decay = raw.get("decay_days")
    floor = raw.get("floor", 0.4)
    try:
        base_value = float(base)
    except (TypeError, ValueError):
        raise RecommendationConfigError("freshness.base must be numeric")
    decay_value: int | None
    if decay in (None, "", 0):
        decay_value = None
    else:
        try:
            decay_value = int(decay)
        except (TypeError, ValueError):
            raise RecommendationConfigError("freshness.decay_days must be an integer")
        if decay_value < 0:
            raise RecommendationConfigError("freshness.decay_days cannot be negative")
    try:
        floor_value = float(floor)
    except (TypeError, ValueError):
        raise RecommendationConfigError("freshness.floor must be numeric")
    if base_value <= 0:
        raise RecommendationConfigError("freshness.base must be positive")
    if floor_value < 0:
        raise RecommendationConfigError("freshness.floor cannot be negative")
    return FreshnessConfig(base=base_value, decay_days=decay_value, floor=floor_value)


def load_product_rules() -> list[ProductRule]:
    payload = _load_yaml(DATA_ROOT / "tag_product_map.yaml")
    entries = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RecommendationConfigError("tag_product_map.yaml must contain a non-empty 'products' list")

    seen_products: set[str] = set()
    rules: list[ProductRule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RecommendationConfigError("Each product entry must be an object")
        product = str(entry.get("product") or "").strip()
        if not product:
            raise RecommendationConfigError("Each product entry must include a product id")
        if product in seen_products:
            raise RecommendationConfigError(f"Duplicate product entry: {product}")
        seen_products.add(product)

        weight_raw = entry.get("weight", 1.0)
        try:
            weight = float(weight_raw)
        except (TypeError, ValueError):
            raise RecommendationConfigError(f"weight for {product} must be numeric")
        if weight <= 0:
            raise RecommendationConfigError(f"weight for {product} must be positive")

        utm_category = str(entry.get("utm_category") or "").strip()
        if not utm_category:
            raise RecommendationConfigError(f"utm_category is required for {product}")
        if utm_category not in _ALLOWED_UTM_CATEGORIES:
            raise RecommendationConfigError(f"utm_category '{utm_category}' for {product} is not supported")

        match_cfg = _parse_match(entry.get("match"))
        freshness_cfg = _parse_freshness(entry.get("freshness"))
        audience_cfg = _parse_audience(entry.get("audience"))

        exclude_tags_raw = entry.get("exclude_tags") or []
        exclude_allergens_raw = entry.get("exclude_allergens") or []
        exclude_tags = frozenset(str(tag).strip() for tag in exclude_tags_raw if tag)
        exclude_allergens = frozenset(str(tag).strip() for tag in exclude_allergens_raw if tag)

        notes = entry.get("notes")
        rules.append(
            ProductRule(
                product_id=product,
                weight=weight,
                utm_category=utm_category,
                match=match_cfg,
                freshness=freshness_cfg,
                audience=audience_cfg,
                exclude_tags=exclude_tags,
                exclude_allergens=exclude_allergens,
                notes=str(notes).strip() if isinstance(notes, str) and notes else None,
            )
        )
    return rules


__all__ = [
    "RecommendationConfigError",
    "load_tag_ontology",
    "load_product_rules",
]
