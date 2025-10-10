"""Utilities for constructing Velavie order links with tracking parameters."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.catalog.loader import product_by_alias, product_by_id
from app.products import BUY_URLS

__all__ = ["build_order_link"]


def _normalize_code(code: str) -> str:
    return str(code or "").strip()


def _coerce_mapping(raw: Mapping[str, object] | None) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    coerced: dict[str, str] = {}
    for key, value in raw.items():
        if not key:
            continue
        if value is None:
            continue
        coerced[str(key)] = str(value)
    return coerced


def _extract_order_payload(product: Mapping[str, object] | None) -> tuple[str | None, dict[str, str]]:
    if not isinstance(product, Mapping):
        return None, {}

    order = product.get("order")
    url: str | None = None
    defaults: dict[str, str] = {}
    if isinstance(order, Mapping):
        candidate = order.get("velavie_link") or order.get("url")
        if isinstance(candidate, str) and candidate.strip():
            url = candidate.strip()
        defaults = _coerce_mapping(order.get("utm"))

    if url is None:
        fallback = product.get("order_url") or product.get("url")
        if isinstance(fallback, str) and fallback.strip():
            url = fallback.strip()

    return url, defaults


def _resolve_product(code: str) -> Mapping[str, object] | None:
    product = product_by_id(code)
    if product:
        return product
    return product_by_alias(code)


def _lookup_fallback(code: str) -> str | None:
    if not BUY_URLS:
        return None
    # BUY_URLS uses legacy uppercase codes.
    legacy = BUY_URLS.get(code) or BUY_URLS.get(code.upper()) or BUY_URLS.get(code.lower())
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()
    return None


def build_order_link(
    code: str,
    *,
    params: Mapping[str, str] | None = None,
    replace: bool = False,
) -> str | None:
    """Return an order link for a product enriched with UTM parameters.

    The lookup prefers the catalog entry (which may contain dynamic overrides)
    and falls back to the legacy ``BUY_URLS`` mapping if necessary.
    """

    canonical = _normalize_code(code)
    if not canonical:
        return None

    product = _resolve_product(canonical)
    base_url, defaults = _extract_order_payload(product)
    if base_url is None:
        base_url = _lookup_fallback(canonical)
        defaults = {}
    if base_url is None:
        return None

    split = urlsplit(base_url)
    query_params: dict[str, str] = {}
    if split.query:
        query_params.update(parse_qsl(split.query, keep_blank_values=True))

    if defaults:
        query_params.update(defaults)

    if params:
        for key, value in params.items():
            if not key:
                continue
            if value is None:
                query_params.pop(key, None)
                continue
            str_key = str(key)
            if replace or str_key not in query_params or not query_params[str_key]:
                query_params[str_key] = str(value)

    encoded = urlencode(query_params, doseq=True)
    return urlunsplit((split.scheme, split.netloc, split.path, encoded, split.fragment))
