"""Telemetry helpers for catalog interactions."""

from __future__ import annotations

import logging
import re
from typing import Iterable

from app.storage import USERS, save_event

LOGGER = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,}")


def _user_source(user_id: int) -> str | None:
    return USERS.get(user_id, {}).get("source")


def _sanitize(value: str, *, limit: int = 128) -> str:
    shortened = value.replace("\n", " ").strip()
    if len(shortened) > limit:
        shortened = shortened[:limit] + "…"
    return _TOKEN_PATTERN.sub("***", shortened)


def log_product_view(user_id: int, product_id: str) -> None:
    """Emit product view telemetry."""

    LOGGER.info("product_view user=%s product=%s", user_id, product_id)
    save_event(user_id, _user_source(user_id), "product_view", {"product_id": product_id})


def log_product_click_buy(user_id: int, product_id: str) -> None:
    """Emit product click-to-buy telemetry."""

    LOGGER.info("product_click_buy user=%s product=%s", user_id, product_id)
    save_event(user_id, _user_source(user_id), "product_click_buy", {"product_id": product_id})


def log_catalog_search(user_id: int, query: str, results: Iterable[str]) -> None:
    """Emit catalog search telemetry."""

    sanitized_query = _sanitize(query)
    result_ids = list(results)
    LOGGER.info(
        "catalog_search user=%s query=%s results=%s",
        user_id,
        sanitized_query,
        result_ids,
    )
    save_event(
        user_id,
        _user_source(user_id),
        "catalog_search",
        {"query": sanitized_query, "results": result_ids},
    )
