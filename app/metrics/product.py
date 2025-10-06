"""Product analytics metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from prometheus_client import Counter, Histogram

__all__ = [
    "record_event",
]


_product_event_total = Counter(
    "product_event_total",
    "Total number of tracked product events",
    labelnames=("event",),
)

_user_signup_total = Counter(
    "product_user_signup_total",
    "Number of users that completed signup",
)

_referral_join_total = Counter(
    "product_referral_join_total",
    "Number of users that joined via referral",
)

_lead_created_total = Counter(
    "product_lead_created_total",
    "Number of captured leads",
)

_purchase_attempt_total = Counter(
    "product_purchase_attempt_total",
    "Number of purchase attempts",
)

_purchase_success_total = Counter(
    "product_purchase_success_total",
    "Number of successful purchases",
)

_feature_use_total = Counter(
    "product_feature_use_total",
    "Number of feature uses",
    labelnames=("feature",),
)

_event_age_days = Histogram(
    "product_event_age_days",
    "Days between signup and subsequent events",
    labelnames=("event",),
    buckets=(0, 1, 2, 3, 7, 14, 30, 60, 90, 180, 365, float("inf")),
)

_signup_at: Dict[int, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _observe_event_age(event: str, user_id: int | None, occurred_at: datetime) -> None:
    if user_id is None:
        return
    started_at = _signup_at.get(user_id)
    if not started_at:
        return
    delta = occurred_at - started_at
    if delta.total_seconds() < 0:
        return
    _event_age_days.labels(event=event).observe(delta.total_seconds() / 86400.0)


def record_event(event: str, user_id: int | None, occurred_at: datetime | None, props: Dict[str, Any]) -> None:
    """Update Prometheus metrics for a product event."""

    ts = occurred_at or _now()
    _product_event_total.labels(event=event).inc()

    if event == "user_signup":
        _user_signup_total.inc()
        if user_id is not None:
            _signup_at[user_id] = ts
        return

    if event == "referral_join":
        _referral_join_total.inc()
        _observe_event_age(event, user_id, ts)
        return

    if event == "lead_created":
        _lead_created_total.inc()
        _observe_event_age(event, user_id, ts)
        return

    if event == "purchase_attempt":
        _purchase_attempt_total.inc()
        _observe_event_age(event, user_id, ts)
        return

    if event == "purchase_success":
        _purchase_success_total.inc()
        _observe_event_age(event, user_id, ts)
        return

    if event.startswith("feature_use"):
        feature = ""
        if ":" in event:
            feature = event.split(":", 1)[1]
        if not feature:
            feature = str(props.get("feature") or "unknown")
        _feature_use_total.labels(feature=feature).inc()
        _observe_event_age("feature_use", user_id, ts)
        return

    # Unknown events still contribute to the timeline histogram.
    _observe_event_age(event, user_id, ts)
