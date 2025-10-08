from __future__ import annotations

from app.catalog.loader import load_catalog
from app.reco import load_product_rules, load_tag_ontology

QUIZ_TAGS = {
    "energy",
    "mitochondria",
    "tonus",
    "support",
    "adaptogens",
    "caffeine",
    "electrolytes",
    "mct",
    "brain-coffee",
    "vitamin-d3",
    "sleep_focus",
    "sleep_support",
    "sleep_ok",
    "overstim",
    "ok",
    "b-complex",
    "recovery",
    "mitup",
}


def test_tag_ontology_contains_quiz_tags() -> None:
    ontology = load_tag_ontology()
    missing = QUIZ_TAGS - set(ontology)
    assert not missing, f"quiz tags without ontology definition: {sorted(missing)}"


def test_product_rules_cover_catalog() -> None:
    catalog = load_catalog()
    rules = load_product_rules()

    catalog_ids = set(catalog["products"].keys())
    rule_ids = {rule.product_id for rule in rules}

    assert len(rules) == len(catalog_ids) == 38
    assert catalog_ids == rule_ids

    ontology = load_tag_ontology()
    known_tags = set(ontology)
    utm_categories = {rule.utm_category for rule in rules}
    for rule in rules:
        assert 0 < rule.weight < 2.5
        assert 0 <= rule.match.threshold <= 1
        assert rule.freshness.base > 0
        assert rule.freshness.floor >= 0
        assert rule.utm_category in utm_categories
        for tag in rule.match.weights:
            assert tag in known_tags
        for tag in rule.exclude_tags:
            assert tag in known_tags

    assert utm_categories == {
        "energy",
        "focus",
        "immunity",
        "sleep",
        "stress",
        "gut",
        "metabolism",
        "beauty",
        "lifestyle",
        "snacks",
    }
