"""In-memory analytics for catalog views and clicks."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Iterable


@dataclass
class CatalogEvent:
    ts: datetime
    type: str  # "view" or "click"
    product_id: str
    campaign: str


_MAX_EVENTS = 5000
_events: Deque[CatalogEvent] = deque(maxlen=_MAX_EVENTS)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_campaign(raw: str | None) -> str:
    """Normalize campaign/category slug for analytics/utm usage."""
    if not raw:
        return "general"
    slug = [ch.lower() if ch.isalnum() else "_" for ch in raw.strip()]
    out = "".join(slug).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "general"


def record_events(product_ids: Iterable[str], campaign: str, event_type: str) -> None:
    campaign_norm = normalize_campaign(campaign)
    now = _utcnow()
    for pid in product_ids:
        if not pid:
            continue
        _events.append(CatalogEvent(ts=now, type=event_type, product_id=pid, campaign=campaign_norm))


def record_view(product_ids: Iterable[str], campaign: str) -> None:
    record_events(product_ids, campaign, "view")


def record_click(product_id: str, campaign: str) -> None:
    record_events([product_id], campaign, "click")


def _aggregate(since: datetime) -> Dict[str, Dict[str, int]]:
    product_views: Counter[str] = Counter()
    product_clicks: Counter[str] = Counter()
    category_views: Counter[str] = Counter()
    category_clicks: Counter[str] = Counter()

    for event in _events:
        if event.ts < since:
            continue
        if event.type == "view":
            product_views[event.product_id] += 1
            category_views[event.campaign] += 1
        elif event.type == "click":
            product_clicks[event.product_id] += 1
            category_clicks[event.campaign] += 1

    return {
        "product_views": product_views,
        "product_clicks": product_clicks,
        "category_views": category_views,
        "category_clicks": category_clicks,
    }


def get_stats() -> Dict[str, Dict[str, Dict[str, int]]]:
    """Return aggregated stats for last day and last week."""
    now = _utcnow()
    day = _aggregate(now - timedelta(days=1))
    week = _aggregate(now - timedelta(days=7))
    return {"day": day, "week": week}
