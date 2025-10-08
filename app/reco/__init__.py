from __future__ import annotations

from typing import Iterable

from .context import CTX, product_lines
from .engine import (
    RecommendationEngine,
    RecommendationResult,
    TagOntology,
    get_engine,
    load_product_map,
    load_tag_ontology,
)

__all__ = [
    "CTX",
    "product_lines",
    "RecommendationEngine",
    "RecommendationResult",
    "TagOntology",
    "load_tag_ontology",
    "load_product_map",
    "get_engine",
    "recommend",
    "recommend_full",
]


def recommend(tags: Iterable[str], *, audience: str | None = None, limit: int = 5) -> list[RecommendationResult]:
    """Return a lightweight recommendation list for the provided tags."""

    engine = get_engine()
    return engine.recommend(tags, audience=audience, limit=limit)


def recommend_full(tags: Iterable[str], *, audience: str | None = None, limit: int = 5) -> list[RecommendationResult]:
    """Return recommendation results with scoring metadata."""

    engine = get_engine()
    return engine.recommend_full(tags, audience=audience, limit=limit)
