"""Utilities for working with UTM parameters."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def add_utm_params(url: str, params: dict[str, str]) -> str:
    """Append UTM parameters to URL preserving existing query parameters."""
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if any(key.lower().startswith("utm_") for key in existing):
        return url  # already contains UTM tags
    merged = existing | params
    new_query = urlencode(merged, doseq=True)
    updated = parsed._replace(query=new_query)
    return urlunparse(updated)
