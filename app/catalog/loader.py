"""Utilities for loading and querying the product catalog."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.catalog.overrides import apply_overrides, load_overrides

CATALOG_DIR = os.path.dirname(__file__)
CATALOG_PATH = os.path.join(CATALOG_DIR, "products.json")
CATALOG_FILE = Path(CATALOG_PATH)
ALIASES_PATH = os.path.join(CATALOG_DIR, "aliases.json")


def _compute_catalog_sha() -> str:
    digest = hashlib.sha1()
    try:
        with open(CATALOG_PATH, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                if not chunk:
                    break
                digest.update(chunk)
    except FileNotFoundError:
        return "missing"
    return digest.hexdigest()


CATALOG_SHA = os.getenv("CATALOG_SHA") or _compute_catalog_sha()


class CatalogError(RuntimeError):
    """Raised when the catalog file cannot be parsed."""


def _read_raw() -> Dict[str, Any]:
    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as exc:  # pragma: no cover - catastrophic misconfig
        raise CatalogError("products.json is missing") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError("products.json is not valid JSON") from exc

    if not isinstance(raw, dict):
        raise CatalogError("products.json must contain an object at the top level")

    items = raw.get("products")
    version = raw.get("version")
    if isinstance(items, list) and items:
        return {"products": items, "version": version}

    # Backwards compatibility: legacy format is a flat mapping id -> metadata.
    if items is None:
        legacy_items = []
        for pid, meta in raw.items():
            if not isinstance(meta, dict):
                continue
            copy = {**meta}
            copy.setdefault("id", pid)
            if "order" not in copy:
                velavie_link = meta.get("order_url") or meta.get("url")
                if velavie_link:
                    copy["order"] = {"velavie_link": velavie_link}
            legacy_items.append(copy)
        if legacy_items:
            return {"products": legacy_items, "version": version}

    raise CatalogError("products.json must contain a non-empty 'products' array")


def _load_manual_aliases() -> Dict[str, str]:
    try:
        with open(ALIASES_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise CatalogError("aliases.json is not valid JSON") from exc

    aliases = payload.get("aliases", payload) if isinstance(payload, dict) else payload

    manual: Dict[str, str] = {}
    if isinstance(aliases, dict):
        items = aliases.items()
    elif isinstance(aliases, list):
        items = []
        for entry in aliases:
            if not isinstance(entry, dict):
                continue
            alias_raw = entry.get("alias") or entry.get("name") or entry.get("source")
            target_raw = entry.get("id") or entry.get("product") or entry.get("target")
            if alias_raw and target_raw:
                items.append((alias_raw, target_raw))
    else:
        items = []

    for alias_raw, target_raw in items:
        alias = str(alias_raw).strip()
        target = str(target_raw).strip()
        if not alias or not target:
            continue
        manual[alias.lower()] = target

    return manual


@lru_cache(maxsize=1)
def load_catalog(refresh: bool = False) -> Dict[str, Any]:
    """Load and index the catalog, optionally bypassing the cache."""

    if refresh:
        load_catalog.cache_clear()  # type: ignore[attr-defined]

    data = _read_raw()
    items: List[Dict[str, Any]] = data["products"]
    version = str(data.get("version") or _derive_version_fallback())

    by_id: Dict[str, Dict[str, Any]] = {}
    by_alias: Dict[str, str] = {}
    ordered_ids: List[str] = []

    overrides = load_overrides()

    for item in items:
        if not isinstance(item, dict):
            continue
        product_id = item.get("id")
        if not isinstance(product_id, str) or not product_id:
            continue
        order_info = item.get("order") or {}
        velavie_link = order_info.get("velavie_link")
        if not isinstance(velavie_link, str) or not velavie_link.strip():
            continue

        canonical = product_id.strip()
        ordered_ids.append(canonical)
        item_with_overrides = apply_overrides(item, overrides.get(canonical, {}))
        by_id[canonical] = item_with_overrides

        aliases = item_with_overrides.get("aliases") or []
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias:
                    by_alias[alias.lower()] = canonical
        by_alias[canonical.lower()] = canonical
        by_alias[canonical.upper()] = canonical

    manual_aliases = _load_manual_aliases()
    for alias, target in manual_aliases.items():
        canonical = by_id.get(target)
        if not canonical:
            continue
        by_alias[alias] = target

    return {
        "products": by_id,
        "aliases": by_alias,
        "ordered": ordered_ids,
        "version": version,
    }


def catalog_version() -> str:
    data = load_catalog()
    version = data.get("version")
    if isinstance(version, str) and version:
        return version
    return _derive_version_fallback()


def _derive_version_fallback() -> str:
    try:
        stat = CATALOG_FILE.stat()
    except FileNotFoundError:
        return "unknown"
    return str(int(stat.st_mtime))


def product_by_id(pid: str) -> Dict[str, Any] | None:
    if not pid:
        return None
    catalog = load_catalog()
    return catalog["products"].get(pid)


def product_by_alias(alias: str) -> Dict[str, Any] | None:
    if not alias:
        return None
    catalog = load_catalog()
    pid = catalog["aliases"].get(alias.lower())
    if not pid:
        return None
    return catalog["products"].get(pid)


def select_by_goals(goals: Iterable[str], limit: int = 6) -> List[Dict[str, Any]]:
    catalog = load_catalog()
    goal_set = {goal.lower() for goal in goals if goal}
    if not goal_set:
        return []

    selected: List[Dict[str, Any]] = []
    for pid in catalog["ordered"]:
        product = catalog["products"][pid]
        product_goals = product.get("goals") or []
        if not isinstance(product_goals, list):
            continue
        if goal_set.intersection({str(goal).lower() for goal in product_goals if goal}):
            selected.append(product)
            if len(selected) >= limit:
                break
    return selected


__all__ = [
    "CatalogError",
    "load_catalog",
    "product_by_id",
    "product_by_alias",
    "catalog_version",
    "select_by_goals",
]
