from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.reco import get_engine, recommend_full
from tools.validate_reco_map import validate_recommendation_map


def test_engine_returns_results() -> None:
    engine = get_engine()
    results = engine.recommend(["energy", "mitochondria"], audience="athlete", limit=3)
    assert results, "engine should return products for energy + mitochondria"
    product_ids = {item.product_id for item in results}
    assert "t8-extra-90" in product_ids


def test_recommendation_full_contains_explain() -> None:
    results = recommend_full(["sleep_support", "magnesium"], audience="office", limit=3)
    assert results, "full recommendation should yield results"
    first = results[0]
    explanation = first.explain()
    assert explanation
    assert "tag_match" in first.factors
    assert first.factors["tag_match"] >= 1.0


def test_order_url_contains_recommend_medium() -> None:
    engine = get_engine()
    result = engine.recommend(["immunity", "vitamin_d3"], audience="wellness", limit=3)[0]
    assert result.order_url
    parsed = urlparse(result.order_url)
    params = parse_qs(parsed.query)
    assert params.get("utm_medium") == ["recommend"]
    assert params.get("utm_content") == [result.product_id]


def test_validate_map_has_no_errors() -> None:
    errors, _warnings = validate_recommendation_map()
    assert not errors
