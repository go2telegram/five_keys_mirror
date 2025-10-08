"""Recommendation toolkit: legacy helpers, rule engine and utilities."""

from __future__ import annotations

from .engine import RecommendationEngine, load_engine
from .legacy import CTX, product_lines
from .links import OrderLinkError, build_order_link
from .loaders import RecommendationConfigError, load_product_rules, load_tag_ontology
from .models import (
    RecommendationCard,
    RecommendationRequest,
    RecommendationResult,
)

__all__ = [
    "CTX",
    "RecommendationCard",
    "RecommendationEngine",
    "RecommendationRequest",
    "RecommendationResult",
    "RecommendationConfigError",
    "OrderLinkError",
    "build_order_link",
    "load_engine",
    "load_product_rules",
    "load_tag_ontology",
    "product_lines",
]
