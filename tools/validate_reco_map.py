"""Validate tag ontology and product mapping for the recommendation engine."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.catalog.api import load_catalog_map
from app.reco import load_product_map, load_tag_ontology


def _format_errors(errors: Iterable[str]) -> str:
    return "\n".join(f"• {message}" for message in errors)


def validate_recommendation_map() -> tuple[list[str], list[str]]:
    """Return validation errors and warnings for recommendation datasets."""

    errors: list[str] = []
    warnings: list[str] = []
    ontology = load_tag_ontology()
    product_map = load_product_map(ontology)

    catalog = load_catalog_map()
    catalog_ids = {pid for pid in catalog.keys()}
    product_ids = set(product_map.keys())

    missing_in_catalog = sorted(product_ids - catalog_ids)
    if missing_in_catalog:
        errors.append(
            "В карте продуктов присутствуют ID, отсутствующие в каталоге: "
            + ", ".join(missing_in_catalog)
        )

    missing_in_map = sorted(catalog_ids - product_ids)
    if missing_in_map:
        errors.append(
            "В карте продуктов отсутствуют позиции из каталога: " + ", ".join(missing_in_map)
        )

    tag_usage: Counter[str] = Counter()
    for pid, profile in product_map.items():
        if not profile.tags:
            errors.append(f"Продукт {pid} не содержит тегов для скоринга")
            continue
        for tag in profile.tags:
            if tag not in ontology:
                errors.append(f"Продукт {pid} использует неизвестный тег '{tag}'")
            tag_usage[tag] += 1

    unused_tags = sorted({spec.id for spec in ontology.tags if tag_usage[spec.id] == 0})
    if unused_tags:
        warnings.append(
            "Ни один продукт не использует следующие теги онтологии: " + ", ".join(unused_tags)
        )

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="не выводить подробный отчёт")
    args = parser.parse_args(argv)

    errors, warnings = validate_recommendation_map()
    if errors:
        if not args.quiet:
            print("❌ Обнаружены проблемы в данных рекомендаций:")
            print(_format_errors(errors))
        return 1

    if not args.quiet:
        ontology = load_tag_ontology()
        product_map = load_product_map(ontology)
        print("✅ Карта рекомендаций валидна.")
        print(f"Продуктов: {len(product_map)}")
        tags = Counter()
        for profile in product_map.values():
            tags.update(profile.tags.keys())
        top_tags = ", ".join(f"{tag}×{count}" for tag, count in tags.most_common(10))
        print(f"Самые популярные теги: {top_tags}")
        if warnings:
            print("⚠️ Предупреждения:")
            print(_format_errors(warnings))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
