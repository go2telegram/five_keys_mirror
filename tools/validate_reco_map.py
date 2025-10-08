"""Validate recommendation ontology and rule consistency."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.catalog.loader import load_catalog
from app.reco import RecommendationConfigError, load_product_rules, load_tag_ontology


def _check_tags_exist(rule_tags: Iterable[str], known: set[str], *, context: str) -> None:
    missing = sorted(tag for tag in rule_tags if tag not in known)
    if missing:
        raise RecommendationConfigError(f"Unknown tag(s) in {context}: {', '.join(missing)}")


def main() -> int:
    ontology = load_tag_ontology()
    known_tags = set(ontology)
    rules = load_product_rules()
    catalog = load_catalog()
    catalog_ids = set(catalog["products"].keys())
    rule_ids = {rule.product_id for rule in rules}

    missing_from_rules = sorted(catalog_ids - rule_ids)
    if missing_from_rules:
        raise RecommendationConfigError(f"No rules found for products: {', '.join(missing_from_rules)}")

    unknown_products = sorted(rule_ids - catalog_ids)
    if unknown_products:
        raise RecommendationConfigError(f"Rules reference unknown products: {', '.join(unknown_products)}")

    for rule in rules:
        _check_tags_exist(rule.match.weights.keys(), known_tags, context=f"match[{rule.product_id}]")
        _check_tags_exist(rule.exclude_tags, known_tags, context=f"exclude[{rule.product_id}]")

    print(f"✅ Recommendation map OK: {len(rules)} products covered.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    try:
        exit_code = main()
    except RecommendationConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1)
    else:
        raise SystemExit(exit_code)
