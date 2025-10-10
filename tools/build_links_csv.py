#!/usr/bin/env python3
"""Generate the default link override CSV from the product catalog."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

CATALOG_PATH = ROOT / "app" / "catalog" / "products.json"
OUTPUT_PATH = ROOT / "app" / "links" / "sets" / "links_set_default.csv"


def _load_products(catalog_path: Path) -> list[dict]:
    try:
        with catalog_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError as exc:  # pragma: no cover - catastrophic misconfig
        raise SystemExit(f"catalog file not found: {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"catalog file is not valid JSON: {catalog_path}") from exc

    items = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise SystemExit("catalog payload must contain a 'products' array")
    return items


def _iter_rows(products: Iterable[dict]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    register_link = (settings.BASE_REGISTER_URL or "").strip()
    rows.append(("register", "", register_link))

    for item in products:
        if not isinstance(item, dict):
            continue
        product_id = item.get("id")
        if not isinstance(product_id, str) or not product_id.strip():
            continue
        order = item.get("order") or {}
        url = ""
        if isinstance(order, dict):
            raw_url = order.get("velavie_link")
            if isinstance(raw_url, str):
                url = raw_url.strip()
        rows.append(("product", product_id.strip(), url))
    return rows


def build_links_csv(catalog_path: Path, output_path: Path) -> None:
    products = _load_products(catalog_path)
    rows = _iter_rows(products)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["type", "id", "url"])
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build default links CSV from catalog")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=CATALOG_PATH,
        help="Path to products.json (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Where to write links_set_default.csv (default: %(default)s)",
    )
    args = parser.parse_args()
    build_links_csv(args.catalog, args.output)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
