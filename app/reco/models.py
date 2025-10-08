"""Dataclasses describing recommendation inputs and rule configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class TagDefinition:
    """Single tag metadata entry from ``tag_ontology.yaml``."""

    key: str
    title: str
    description: str
    group: str
    sources: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchConfig:
    """Configuration describing how a product rule matches user tags."""

    weights: Mapping[str, float]
    threshold: float

    def score(self, tags: Iterable[str]) -> tuple[float, list[str], list[str]]:
        """Compute the match ratio against a set of tags.

        Returns a tuple ``(ratio, matched_tags, missing_tags)``.
        ``ratio`` is normalized between 0 and 1.
        """

        tag_set = {tag.strip() for tag in tags if tag}
        matched: list[str] = []
        missing: list[str] = []
        total_weight = 0.0
        matched_weight = 0.0
        for tag, weight in self.weights.items():
            total_weight += max(0.0, float(weight))
            if tag in tag_set:
                matched.append(tag)
                matched_weight += max(0.0, float(weight))
            else:
                missing.append(tag)
        if total_weight <= 0:
            return 0.0, matched, missing
        ratio = matched_weight / total_weight
        return ratio, matched, missing


@dataclass(frozen=True)
class AudienceBoost:
    """Audience targeting rule that multiplies the score when satisfied."""

    factor: float
    any_of: frozenset[str] = frozenset()
    all_of: frozenset[str] = frozenset()
    label: str | None = None

    def applies(self, audience: Iterable[str]) -> bool:
        pool = {item.strip() for item in audience if item}
        if self.any_of and not (self.any_of & pool):
            return False
        if self.all_of and not self.all_of <= pool:
            return False
        return bool(self.any_of or self.all_of)


@dataclass(frozen=True)
class FreshnessConfig:
    """Controls how the freshness multiplier is computed."""

    base: float = 1.0
    decay_days: int | None = None
    floor: float = 0.4

    def score(self, last_seen: datetime | None, *, now: datetime | None = None) -> float:
        from datetime import datetime as dt

        base = max(0.0, float(self.base))
        floor = max(0.0, float(self.floor))
        if last_seen is None or self.decay_days in (None, 0):
            return max(base, floor)
        if now is None:
            now = dt.utcnow()
        elapsed = (now - last_seen).total_seconds()
        if elapsed < 0:
            return max(base, floor)
        days = elapsed / 86400.0
        if days >= float(self.decay_days):
            return max(base, floor)
        ratio = max(0.0, days / float(self.decay_days))
        return max(floor, base * ratio)


@dataclass(frozen=True)
class ProductRule:
    """Single product recommendation rule."""

    product_id: str
    weight: float
    utm_category: str
    match: MatchConfig
    freshness: FreshnessConfig
    audience: tuple[AudienceBoost, ...] = ()
    exclude_tags: frozenset[str] = frozenset()
    exclude_allergens: frozenset[str] = frozenset()
    notes: str | None = None


@dataclass
class RecommendationRequest:
    """Input payload used by :class:`RecommendationEngine`."""

    tags: Sequence[str]
    audience: Sequence[str] = ()
    allergies: Sequence[str] = ()
    limit: int = 5
    min_score: float = 0.2
    last_seen: Mapping[str, datetime] | None = None
    include_explain: bool = False


@dataclass
class RecommendationCard:
    """Card data returned by the recommendation engine."""

    product_id: str
    code: str
    name: str
    short: str
    order_url: str | None
    images: Sequence[str]
    props: Sequence[str]
    score: float
    weight: float
    tag_match: float
    audience_boost: float
    freshness: float
    matched_tags: list[str] = field(default_factory=list)
    missing_tags: list[str] = field(default_factory=list)
    utm_category: str = ""


@dataclass
class RecommendationResult:
    """Structured response for ``/recommend`` and ``/recommend_full``."""

    cards: list[RecommendationCard]
    excluded: list[dict]
    explain: dict | None = None
