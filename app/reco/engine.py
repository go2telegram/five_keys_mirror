"""Rule-based recommendation engine built on tag ontology."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from app.catalog.api import product_meta

from .links import build_order_link
from .loaders import RecommendationConfigError, load_product_rules, load_tag_ontology
from .models import AudienceBoost, ProductRule, RecommendationCard, RecommendationRequest, RecommendationResult, TagDefinition


class RecommendationEngine:
    """Evaluate product rules against incoming tag payloads."""

    def __init__(self, *, rules: Sequence[ProductRule] | None = None, tags: dict[str, TagDefinition] | None = None) -> None:
        self._rules = list(rules) if rules is not None else load_product_rules()
        self._tags = dict(tags) if tags is not None else load_tag_ontology()

    @property
    def rules(self) -> list[ProductRule]:
        return list(self._rules)

    @property
    def tags(self) -> dict[str, TagDefinition]:
        return dict(self._tags)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        if request.limit <= 0:
            raise ValueError("limit must be positive")
        tag_set = {tag.strip() for tag in request.tags if tag}
        allergy_set = {item.strip() for item in request.allergies if item}
        audience_set = {item.strip() for item in request.audience if item}
        seen = request.last_seen or {}
        now = datetime.utcnow()

        cards: list[RecommendationCard] = []
        excluded: list[dict] = []
        explain_payload: list[dict] = []
        explain_sources: set[str] = set()

        for rule in self._rules:
            exclusion_reason = self._check_exclusions(rule, tag_set, allergy_set)
            if exclusion_reason:
                excluded.append({"product_id": rule.product_id, "reason": exclusion_reason})
                continue

            tag_match, matched_tags, missing_tags = rule.match.score(tag_set)
            if tag_match < max(0.0, rule.match.threshold):
                continue

            audience_boost, triggers = self._audience_boost(rule.audience, audience_set)
            freshness = rule.freshness.score(seen.get(rule.product_id), now=now)
            score = rule.weight * tag_match * audience_boost * freshness
            if score < request.min_score:
                continue

            meta = product_meta(rule.product_id)
            if not meta:
                excluded.append(
                    {
                        "product_id": rule.product_id,
                        "reason": "missing_metadata",
                    }
                )
                continue

            order_url = build_order_link(rule.product_id, rule.utm_category)
            card = RecommendationCard(
                product_id=rule.product_id,
                code=meta.get("code", rule.product_id),
                name=meta.get("name", rule.product_id),
                short=meta.get("short", ""),
                order_url=order_url,
                images=list(meta.get("images", []) or []),
                props=list(meta.get("props", []) or []),
                score=score,
                weight=rule.weight,
                tag_match=tag_match,
                audience_boost=audience_boost,
                freshness=freshness,
                matched_tags=matched_tags,
                missing_tags=missing_tags,
                utm_category=rule.utm_category,
            )
            cards.append(card)

            if request.include_explain:
                explain_payload.append(
                    {
                        "product_id": rule.product_id,
                        "score": score,
                        "weight": rule.weight,
                        "tag_match": tag_match,
                        "audience_boost": audience_boost,
                        "freshness": freshness,
                        "matched_tags": matched_tags,
                        "missing_tags": missing_tags,
                        "audience_triggers": triggers,
                        "utm_category": rule.utm_category,
                        "notes": rule.notes,
                    }
                )
                for matched_tag in matched_tags:
                    definition = self._tags.get(matched_tag)
                    if not definition:
                        continue
                    explain_sources.update(definition.sources)

        cards.sort(key=lambda card: card.score, reverse=True)
        cards = cards[: request.limit]

        if request.include_explain:
            explain = {
                "products": explain_payload,
                "sources": sorted(explain_sources),
            }
        else:
            explain = None
        return RecommendationResult(cards=cards, excluded=excluded, explain=explain)

    @staticmethod
    def _check_exclusions(rule: ProductRule, tags: set[str], allergies: set[str]) -> str | None:
        if rule.exclude_tags and rule.exclude_tags & tags:
            return "tag_exclusion"
        if rule.exclude_allergens and rule.exclude_allergens & allergies:
            return "allergen"
        return None

    @staticmethod
    def _audience_boost(boosts: Sequence[AudienceBoost], audience: set[str]) -> tuple[float, list[str]]:
        factor = 1.0
        triggers: list[str] = []
        for boost in boosts:
            if boost.applies(audience):
                factor *= boost.factor
                if boost.label:
                    triggers.append(boost.label)
        return factor, triggers


def load_engine() -> RecommendationEngine:
    """Convenience helper mirroring legacy import style."""

    return RecommendationEngine()


__all__ = ["RecommendationEngine", "RecommendationConfigError", "load_engine"]
