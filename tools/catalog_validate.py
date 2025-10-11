#!/usr/bin/env python3
"""CLI helper that validates products.json against the catalog schema."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from tools.catalog_build import CatalogValidationError, validate_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the catalog JSON file against the bundled schema.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to the catalog JSON file (default: app/catalog/products.json)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to the catalog schema JSON file (default: app/catalog/schema.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = validate_catalog(args.source, schema_path=args.schema)
    except CatalogValidationError as exc:
        parser.exit(status=1, message=f"error: {exc}\n")
    products = payload.get("products")
    count = len(products) if isinstance(products, list) else 0
    parser.exit(status=0, message=f"Catalog OK ({count} products)\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
