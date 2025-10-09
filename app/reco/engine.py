"""Rule-based recommendation engine for AI plan prompts."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.catalog.loader import load_catalog
from app.utils.cards import build_order_link

log = logging.getLogger("reco.engine")

_CATEGORIES_PATH = Path("app/reco/categories.yaml")
_DEFAULT_UTM = "catalog"


def _normalize_tag(tag: str) -> str:
    return str(tag).strip().lower().replace("-", "_")


@lru_cache(maxsize=1)
def _load_categories() -> dict[str, dict[str, Any]]:
    try:
        raw = yaml.safe_load(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:  # pragma: no cover - deployment guard
        log.warning("categories.yaml missing; fallback to defaults")
        return {}
    except Exception:  # pragma: no cover - defensive logging
        log.exception("Failed to parse categories.yaml")
        return {}

    categories: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for name, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            utm = str(payload.get("utm_category") or name or _DEFAULT_UTM)
            tags = [
                _normalize_tag(tag)
                for tag in payload.get("tags", [])
                if isinstance(tag, str) and tag.strip()
            ]
            categories[_normalize_tag(str(name))] = {
                "utm_category": utm,
                "tags": tags,
            }
    return categories


def _match_categories(product_tags: list[str]) -> list[tuple[str, dict[str, Any]]]:
    if not product_tags:
        return []
    normalized = {_normalize_tag(tag) for tag in product_tags if tag}
    matched: list[tuple[str, dict[str, Any]]] = []
    for name, info in _load_categories().items():
        category_tags = set(info.get("tags", []))
        if normalized.intersection(category_tags):
            matched.append((name, info))
    return matched


def _compose_reason(title: str, product: dict[str, Any], categories: list[tuple[str, dict[str, Any]]]) -> str:
    short = product.get("short") or product.get("description")
    reasons: list[str] = []
    if categories:
        names = ", ".join(name for name, _ in categories[:2])
        reasons.append(f"Фокус: {names}")
    if short:
        reasons.append(str(short))
    helps = product.get("how_it_helps") or product.get("helps_text")
    if isinstance(helps, str):
        reasons.append(helps)
    return "; ".join(reasons) or f"Базовая поддержка с {title}."


async def get_reco(user_id: int, limit: int = 5, verbose: bool = False) -> list[dict[str, Any]]:
    """Return top-N products with metadata for AI plan prompts."""

    del user_id  # rule-based engine currently static; keep signature for future use
    catalog = load_catalog()
    ordered = catalog.get("ordered", [])
    products = catalog.get("products", {})
    results: list[dict[str, Any]] = []

    for pid in ordered:
        product = products.get(pid)
        if not isinstance(product, dict):
            continue
        title = product.get("title") or product.get("name")
        if not title:
            continue
        tags = [str(tag).strip().lower() for tag in product.get("tags", []) if tag]
        matched = _match_categories(tags)
        utm_category = matched[0][1].get("utm_category") if matched else _DEFAULT_UTM
        reason = _compose_reason(title, product, matched)
        item = {
            "id": pid,
            "title": title,
            "utm_category": utm_category,
            "tags": tags,
            "why": reason,
            "buy_url": build_order_link(pid, utm_category),
        }
        results.append(item)
        if len(results) >= limit:
            break

    if verbose:
        log.debug("get_reco produced %s items", len(results))

    return results


__all__ = ["get_reco"]
