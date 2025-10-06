"""Utilities for working with the product catalog."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "products.json"
SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "products.schema.json"


def _load_catalog() -> List[dict]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - deployment misconfiguration
        raise RuntimeError(
            f"Catalog file not found: {CATALOG_PATH}. Run `make build-products`."
        ) from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt file
        raise RuntimeError(f"Invalid JSON in {CATALOG_PATH}: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError(f"Catalog must be a list, got {type(data).__name__}")
    return data


def _build_products(raw: List[dict]) -> Dict[str, dict]:
    products: Dict[str, dict] = {}
    for item in raw:
        pid = item.get("id")
        if not pid:
            continue
        name = item.get("name", pid)
        short = item.get("short", "")
        usage = item.get("usage", "")
        bullets: List[str] = []
        if short:
            bullets.append(short)
        if usage:
            bullets.append(usage)
        if not bullets:
            bullets = [""]

        product = {
            "id": pid,
            "title": name,
            "name": name,
            "short": short,
            "description": item.get("description", ""),
            "usage": usage,
            "contra": item.get("contra", ""),
            "buy_url": item.get("buy_url", ""),
            "category": item.get("category"),
            "tags": item.get("tags", []),
            "image": item.get("image", ""),
            "image_url": item.get("image", ""),
            "bullets": bullets,
        }
        products[pid] = product
    return products


def _build_goal_map(raw: List[dict]) -> Dict[str, List[str]]:
    goal_map: Dict[str, List[str]] = defaultdict(list)
    for item in raw:
        category = item.get("category")
        pid = item.get("id")
        if category and pid:
            goal_map[category].append(pid)
    return dict(goal_map)


_RAW_PRODUCTS = _load_catalog()
PRODUCTS = _build_products(_RAW_PRODUCTS)
BUY_URLS = {pid: data.get("buy_url", "") for pid, data in PRODUCTS.items() if data.get("buy_url")}
GOAL_MAP = _build_goal_map(_RAW_PRODUCTS)

__all__ = ["PRODUCTS", "BUY_URLS", "GOAL_MAP", "CATALOG_PATH", "SCHEMA_PATH"]
