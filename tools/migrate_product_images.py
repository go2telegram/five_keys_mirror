#!/usr/bin/env python3
"""Normalize the product images directory structure."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import argparse
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_products

DEFAULT_IMAGES_DIR = ROOT / "app" / "catalog" / "images" / "products"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help="Path to the product images directory (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    images_dir = args.images_dir
    if not images_dir.exists():
        logging.info("Images directory %s does not exist; nothing to migrate", images_dir)
        return 0

    build_products.normalize_images_directory(images_dir)
    logging.info("Images directory %s normalized", images_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
