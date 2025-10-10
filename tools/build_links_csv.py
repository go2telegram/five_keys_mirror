"""Generate default links CSV for dev_up."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PRODUCTS_PATH = Path("app/catalog/products.json")
OUTPUT_PATH = Path("app/links/sets/links_set_default.csv")
DEFAULT_REGISTER_URL = "https://vilavi.com/reg/XXXXXX"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build links_set_default.csv")
    parser.add_argument(
        "--products-path",
        type=Path,
        default=PRODUCTS_PATH,
        help="Path to products.json (default: app/catalog/products.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Destination CSV path (default: app/links/sets/links_set_default.csv)",
    )
    parser.add_argument(
        "--base-register",
        dest="base_register",
        default=None,
        help="Override BASE_REGISTER_URL env var",
    )
    return parser.parse_args(argv)


def load_products(path: Path) -> Iterable[Mapping[str, object]]:
    data = json.loads(path.read_text("utf-8"))
    products = data.get("products")
    if not isinstance(products, list):
        raise ValueError("products.json must contain a list under 'products'")
    return products


def resolve_register_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    env_value = os.getenv("BASE_REGISTER_URL", "").strip()
    return env_value or DEFAULT_REGISTER_URL


def extract_order_url(product: Mapping[str, object]) -> str:
    order = product.get("order") if isinstance(product, Mapping) else None
    if isinstance(order, Mapping):
        velavie_link = order.get("velavie_link")
        if isinstance(velavie_link, str):
            return velavie_link
    if isinstance(order, str):
        return order
    return ""


def write_csv(
    output_path: Path, register_url: str, products: Iterable[Mapping[str, object]]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["type", "id", "url"])
        writer.writerow(["register", "", register_url])
        for product in products:
            product_id = product.get("id") if isinstance(product, Mapping) else None
            if not isinstance(product_id, str):
                continue
            writer.writerow(["product", product_id, extract_order_url(product)])


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    products = load_products(args.products_path)
    register_url = resolve_register_url(args.base_register)
    write_csv(args.output, register_url, products)


if __name__ == "__main__":
    main()
