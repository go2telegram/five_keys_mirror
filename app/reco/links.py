"""Utilities for normalising product order links with UTM parameters."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.catalog.loader import product_by_id

DEFAULT_UTM_SOURCE = "tg_bot"
DEFAULT_UTM_MEDIUM = "recommend"


class OrderLinkError(RuntimeError):
    """Raised when an order link cannot be constructed."""


def build_order_link(product_id: str, utm_category: str) -> str:
    """Return a normalized Velavie link with campaign parameters."""

    product = product_by_id(product_id)
    if not product:
        raise OrderLinkError(f"Unknown product: {product_id}")
    order = product.get("order") or {}
    base_url = order.get("velavie_link")
    if not isinstance(base_url, str) or not base_url:
        raise OrderLinkError(f"Product {product_id} does not contain an order link")

    parsed = urlparse(base_url)
    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_pairs.update(
        {
            "utm_source": DEFAULT_UTM_SOURCE,
            "utm_medium": DEFAULT_UTM_MEDIUM,
            "utm_campaign": utm_category,
            "utm_content": product_id,
        }
    )
    encoded_query = urlencode(query_pairs, doseq=True)
    rebuilt = parsed._replace(query=encoded_query)
    return urlunparse(rebuilt)


__all__ = ["build_order_link", "OrderLinkError"]
