from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import yaml

from slugify import slugify

from app.catalog.api import load_catalog_map
from app.config import settings

from .context import product_lines

_TAG_PATH = Path(__file__).with_name("tag_ontology.yaml")
_PRODUCT_PATH = Path(__file__).with_name("tag_product_map.yaml")


@dataclass(frozen=True)
class TagSpec:
    """Metadata describing a single tag in the ontology."""

    id: str
    title: str
    description: str
    weight: float = 1.0
    group: str | None = None


class TagOntology:
    """Resolve tag identifiers and expose metadata for scoring."""

    def __init__(self, specs: dict[str, TagSpec], aliases: dict[str, str]):
        self._specs = specs
        self._aliases = aliases

    @classmethod
    def from_payload(cls, payload: dict) -> "TagOntology":
        tags_raw = payload.get("tags") or {}
        if not isinstance(tags_raw, dict):
            raise ValueError("tag_ontology: 'tags' must be a mapping")

        specs: dict[str, TagSpec] = {}
        alias_map: dict[str, str] = {}

        for raw_id, raw_spec in tags_raw.items():
            if not isinstance(raw_spec, dict):
                continue
            tag_id = str(raw_id).strip().lower()
            if not tag_id:
                continue
            title = str(raw_spec.get("title") or raw_id)
            description = str(raw_spec.get("description") or title)
            try:
                weight = float(raw_spec.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            group = raw_spec.get("group")
            if isinstance(group, str):
                group = group.strip() or None
            specs[tag_id] = TagSpec(
                id=tag_id,
                title=title,
                description=description,
                weight=weight if weight > 0 else 1.0,
                group=group,
            )
            aliases = raw_spec.get("aliases") or []
            if isinstance(aliases, (list, tuple, set)):
                for alias in aliases:
                    if not isinstance(alias, str):
                        continue
                    alias_map[alias.strip().lower()] = tag_id
            elif isinstance(aliases, str):
                alias_map[aliases.strip().lower()] = tag_id

        global_aliases = payload.get("aliases") or {}
        if isinstance(global_aliases, dict):
            for alias, target in global_aliases.items():
                alias_map[str(alias).strip().lower()] = str(target).strip().lower()

        return cls(specs, alias_map)

    def resolve(self, tag: str | None) -> str | None:
        if not tag:
            return None
        key = str(tag).strip().lower()
        if not key:
            return None
        if key in self._specs:
            return key
        return self._aliases.get(key)

    def get(self, tag: str) -> TagSpec | None:
        canonical = self.resolve(tag)
        if canonical is None:
            return None
        return self._specs.get(canonical)

    def label(self, tag: str) -> str:
        spec = self._specs.get(tag)
        return spec.title if spec else tag

    def describe(self, tag: str) -> str:
        spec = self._specs.get(tag)
        return spec.description if spec else ""

    def weight(self, tag: str) -> float:
        spec = self._specs.get(tag)
        return spec.weight if spec else 1.0

    def __contains__(self, tag: str) -> bool:
        canonical = self.resolve(tag)
        return canonical in self._specs if canonical else False

    @property
    def tags(self) -> Sequence[TagSpec]:
        return tuple(self._specs.values())


@dataclass
class ProductProfile:
    """Configuration describing how a product participates in recommendations."""

    id: str
    category: str
    weight: float
    freshness: float
    tags: dict[str, float]
    audience_boost: dict[str, float] = field(default_factory=dict)


@dataclass
class TagMatch:
    tag: str
    label: str
    score: float
    tag_weight: float
    product_weight: float
    description: str


@dataclass
class RecommendationResult:
    product_id: str
    title: str
    short: str
    order_url: str | None
    score: float
    factors: dict[str, float]
    matched_tags: list[TagMatch]
    category: str | None = None

    def to_summary(self) -> dict:
        return {
            "id": self.product_id,
            "title": self.title,
            "short": self.short,
            "order_url": self.order_url,
            "score": round(self.score, 4),
        }

    def to_full(self) -> dict:
        return {
            **self.to_summary(),
            "factors": {key: round(value, 4) for key, value in self.factors.items()},
            "matched_tags": [
                {
                    "tag": match.tag,
                    "title": match.label,
                    "score": round(match.score, 4),
                    "tag_weight": round(match.tag_weight, 4),
                    "product_weight": round(match.product_weight, 4),
                    "description": match.description,
                }
                for match in self.matched_tags
            ],
        }

    def explain(self) -> str:
        reasons: list[str] = []
        if self.matched_tags:
            tag_lines = ", ".join(f"{match.label} (+{match.score:.2f})" for match in self.matched_tags)
            reasons.append(f"Совпадения по тегам: {tag_lines}.")
        weight = self.factors.get("weight")
        if weight and abs(weight - 1.0) > 1e-6:
            reasons.append(f"Базовый вес продукта: {weight:.2f}.")
        audience_boost = self.factors.get("audience_boost")
        if audience_boost and abs(audience_boost - 1.0) > 1e-6:
            reasons.append(f"Адаптация под аудиторию: ×{audience_boost:.2f}.")
        freshness = self.factors.get("freshness")
        if freshness and abs(freshness - 1.0) > 1e-6:
            reasons.append(f"Фактор актуальности: ×{freshness:.2f}.")
        if not reasons:
            reasons.append("Поддерживает основные запросы пользователя по собранным тегам.")
        return " ".join(reasons)


class RecommendationEngine:
    """Score products against user tags using weighted rules."""

    def __init__(self, ontology: TagOntology, products: dict[str, ProductProfile]):
        self.ontology = ontology
        self.products = products
        self.catalog = load_catalog_map()

    def _catalog_meta(self, product_id: str) -> tuple[str, str, str | None, str | None]:
        product = self.catalog.get(product_id) or {}
        title = product.get("title") or product.get("name") or product_id
        short = product.get("short") or ""
        order = product.get("order") or {}
        order_url = order.get("velavie_link") or order.get("url")
        category = product.get("category")
        if isinstance(category, dict):
            slug = category.get("slug") or category.get("id") or category.get("name")
        else:
            slug = category
        category_slug = slugify(slug or "recommend", lowercase=True, language="ru")
        return title, short, order_url, category_slug

    def recommend(
        self,
        tags: Iterable[str],
        *,
        audience: str | None = None,
        limit: int = 5,
    ) -> list[RecommendationResult]:
        normalized_tags: list[str] = []
        for tag in tags:
            resolved = self.ontology.resolve(tag)
            if resolved:
                normalized_tags.append(resolved)
        if not normalized_tags:
            return []

        audience_key = audience.strip().lower() if isinstance(audience, str) else None
        unique_tags = {tag: normalized_tags.count(tag) for tag in set(normalized_tags)}

        limit = max(3, min(limit, 5))

        results: list[RecommendationResult] = []
        for profile in self.products.values():
            matches: list[TagMatch] = []
            tag_score = 0.0
            for tag, count in unique_tags.items():
                product_weight = profile.tags.get(tag)
                if product_weight is None:
                    continue
                tag_weight = self.ontology.weight(tag)
                contribution = product_weight * tag_weight * count
                tag_score += contribution
                matches.append(
                    TagMatch(
                        tag=tag,
                        label=self.ontology.label(tag),
                        score=contribution,
                        tag_weight=tag_weight,
                        product_weight=product_weight,
                        description=self.ontology.describe(tag),
                    )
                )

            if not matches:
                continue

            weight_factor = profile.weight
            tag_match_factor = 1.0 + tag_score
            audience_factor = 1.0
            if audience_key:
                audience_factor = profile.audience_boost.get(audience_key, 1.0)
            freshness_factor = profile.freshness
            total_score = weight_factor * tag_match_factor * audience_factor * freshness_factor

            title, short, order_url, category_slug = self._catalog_meta(profile.id)
            order_url = normalize_recommendation_url(order_url, profile.id, category_slug)
            matches.sort(key=lambda item: item.score, reverse=True)
            result = RecommendationResult(
                product_id=profile.id,
                title=title,
                short=short,
                order_url=order_url,
                score=total_score,
                factors={
                    "weight": weight_factor,
                    "tag_match": tag_match_factor,
                    "audience_boost": audience_factor,
                    "freshness": freshness_factor,
                },
                matched_tags=matches,
                category=category_slug,
            )
            results.append(result)

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def recommend_full(
        self,
        tags: Iterable[str],
        *,
        audience: str | None = None,
        limit: int = 5,
    ) -> list[RecommendationResult]:
        return self.recommend(tags, audience=audience, limit=limit)

    def explain_plan(self, codes: Sequence[str], context: str) -> list[str]:
        return product_lines(codes, context)


def normalize_recommendation_url(url: str | None, product_id: str, category_slug: str | None) -> str | None:
    if not url:
        return settings.velavie_url or url

    parsed = urlparse(url)
    quoted_path = parsed.path or ""
    if quoted_path:
        quoted_path = "/".join(part for part in quoted_path.split("/"))

    params = parse_qs(parsed.query, keep_blank_values=True)
    params["utm_source"] = ["tg_bot"]
    params["utm_medium"] = ["recommend"]
    params["utm_content"] = [product_id]
    campaign = category_slug or "recommend"
    params["utm_campaign"] = [slugify(campaign, lowercase=True, language="ru")]

    normalized_query = urlencode(params, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            quoted_path,
            parsed.params,
            normalized_query,
            parsed.fragment,
        )
    )


def load_tag_ontology() -> TagOntology:
    payload = yaml.safe_load(_TAG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("tag_ontology.yaml must contain a mapping")
    return TagOntology.from_payload(payload)


def load_product_map(ontology: TagOntology) -> dict[str, ProductProfile]:
    payload = yaml.safe_load(_PRODUCT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("tag_product_map.yaml must contain a mapping")
    items = payload.get("products")
    if not isinstance(items, list):
        raise ValueError("tag_product_map.yaml must define 'products' as a list")

    profiles: dict[str, ProductProfile] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("id") or "").strip()
        if not product_id:
            continue
        category = str(entry.get("category") or "recommend")
        try:
            weight = float(entry.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        if weight <= 0:
            weight = 1.0
        try:
            freshness = float(entry.get("freshness", 1.0))
        except (TypeError, ValueError):
            freshness = 1.0
        if freshness <= 0:
            freshness = 1.0
        tags_raw = entry.get("tags") or {}
        tag_weights: dict[str, float] = {}
        if isinstance(tags_raw, dict):
            for tag_name, raw_weight in tags_raw.items():
                resolved = ontology.resolve(tag_name)
                if not resolved:
                    continue
                try:
                    tag_weight = float(raw_weight)
                except (TypeError, ValueError):
                    tag_weight = 1.0
                if tag_weight <= 0:
                    continue
                tag_weights[resolved] = tag_weight
        audience_map: dict[str, float] = {}
        raw_audience = entry.get("audience") or {}
        if isinstance(raw_audience, dict):
            for key, value in raw_audience.items():
                try:
                    coeff = float(value)
                except (TypeError, ValueError):
                    continue
                if coeff <= 0:
                    continue
                audience_map[str(key).strip().lower()] = coeff
        profiles[product_id] = ProductProfile(
            id=product_id,
            category=str(category),
            weight=weight,
            freshness=freshness,
            tags=tag_weights,
            audience_boost=audience_map,
        )
    return profiles


@lru_cache(maxsize=1)
def get_engine() -> RecommendationEngine:
    ontology = load_tag_ontology()
    product_map = load_product_map(ontology)
    return RecommendationEngine(ontology, product_map)


__all__ = [
    "RecommendationEngine",
    "RecommendationResult",
    "TagOntology",
    "TagSpec",
    "TagMatch",
    "get_engine",
    "load_product_map",
    "load_tag_ontology",
    "normalize_recommendation_url",
]
