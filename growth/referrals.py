"""Referral tracking helpers.

This module centralises referral link generation, parameter validation,
anti-fraud friendly logging and aggregated metrics required by the growth
loop.  All data lives in-memory because the current bot runs without a
persistent database.  The structures are kept intentionally simple so
that they can later be swapped with a repository-backed implementation
without touching the public API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional
from urllib.parse import urlencode

_ALLOWED_SRC_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-.")
_DEFAULT_CHANNEL = "organic"


@dataclass(slots=True)
class ReferralEvent:
    """A single interaction inside the referral funnel."""

    kind: str
    referrer_id: int
    referred_id: Optional[int]
    channel: str
    ts: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)


# In-memory event store; append-only for auditability.
_EVENT_LOG: List[ReferralEvent] = []

# Cache for quick per-user stats.  Each value holds aggregated counters.
_USER_STATS: MutableMapping[int, Dict[str, int]] = {}

# Latest computed viral coefficient, exposed to Grafana.
_LAST_VIRAL_K: float = 0.0


class ReferralValidationError(ValueError):
    """Raised when incoming referral parameters look suspicious."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_channel(channel: Optional[str]) -> str:
    if not channel:
        return _DEFAULT_CHANNEL
    channel = channel.strip().lower()
    if not channel:
        return _DEFAULT_CHANNEL
    if any(ch not in _ALLOWED_SRC_CHARS for ch in channel):
        raise ReferralValidationError(
            f"Unsupported channel '{channel}'. Only a-z, 0-9, -_. are allowed."
        )
    return channel


def generate_referral_link(bot_username: str, ref_code: str, channel: Optional[str] = None) -> str:
    """Compose a shareable referral link with validated utm parameters."""

    channel = _normalise_channel(channel)
    clean_code = str(ref_code).strip()
    if not clean_code:
        raise ReferralValidationError("Empty referral code is not allowed")
    query = urlencode({"ref": clean_code, "src": channel})
    return f"https://t.me/{bot_username}?{query}"


def validate_payload(payload: Mapping[str, str]) -> tuple[str, str]:
    """Validate raw query parameters coming from Telegram deep-linking."""

    ref = payload.get("ref")
    src = payload.get("src")
    if not ref:
        raise ReferralValidationError("Missing 'ref' parameter")
    channel = _normalise_channel(src)
    clean_ref = ref.strip()
    if not clean_ref:
        raise ReferralValidationError("Empty 'ref' parameter")
    if len(clean_ref) > 64:
        raise ReferralValidationError("Referral code is too long")
    return clean_ref, channel


def log_referral_event(
    kind: str,
    referrer_id: int,
    *,
    referred_id: Optional[int] = None,
    channel: Optional[str] = None,
    ts: Optional[datetime] = None,
    metadata: Optional[Mapping[str, object]] = None,
) -> ReferralEvent:
    """Persist a referral event and refresh cached aggregates.

    Parameters
    ----------
    kind:
        `click`, `join`, `conversion` or any other agreed upon stage.
    referrer_id:
        User id of the referrer.
    referred_id:
        Telegram id of the invited user if known.
    channel:
        Marketing channel (stories, reels, etc.).
    ts:
        Explicit timestamp. When omitted the current UTC timestamp is used.
    metadata:
        Any debug information required by downstream anti-fraud tooling.
    """

    if kind not in {"click", "join", "conversion"}:
        raise ReferralValidationError(f"Unsupported referral event kind: {kind}")
    channel = _normalise_channel(channel)
    event = ReferralEvent(
        kind=kind,
        referrer_id=referrer_id,
        referred_id=referred_id,
        channel=channel,
        ts=ts or _now(),
        metadata=dict(metadata or {}),
    )
    _EVENT_LOG.append(event)

    stats = _USER_STATS.setdefault(referrer_id, {
        "clicks": 0,
        "joins": 0,
        "conversions": 0,
    })
    if kind == "click":
        stats["clicks"] += 1
    elif kind == "join":
        stats["joins"] += 1
    elif kind == "conversion":
        stats["conversions"] += 1

    # Refresh the global viral coefficient on every logged event to keep the
    # Grafana metric hot.  We calculate using the last 30 days by default.
    compute_viral_k(window=timedelta(days=30))
    return event


def get_user_stats(user_id: int, *, window: Optional[timedelta] = None) -> Dict[str, int]:
    """Retrieve aggregated counters for the given user."""

    if window is None:
        return dict(_USER_STATS.get(user_id, {"clicks": 0, "joins": 0, "conversions": 0}))

    since = _now() - window
    clicks = joins = conversions = 0
    for event in _EVENT_LOG:
        if event.referrer_id != user_id or event.ts < since:
            continue
        if event.kind == "click":
            clicks += 1
        elif event.kind == "join":
            joins += 1
        elif event.kind == "conversion":
            conversions += 1
    return {"clicks": clicks, "joins": joins, "conversions": conversions}


def _iter_events_since(window: Optional[timedelta]) -> Iterable[ReferralEvent]:
    if window is None:
        yield from _EVENT_LOG
    else:
        since = _now() - window
        for event in _EVENT_LOG:
            if event.ts >= since:
                yield event


def compute_viral_k(*, window: Optional[timedelta] = None, active_users: Optional[int] = None) -> float:
    """Calculate the viral coefficient K for dashboards.

    The default calculation looks at the provided window (30 days when used
    from :func:`log_referral_event`) and applies the classic formula:

        viral_K = (avg invites per user) * (conversion rate)

    Where invites == joins and conversion == conversions / joins.
    """

    global _LAST_VIRAL_K

    events = list(_iter_events_since(window))
    if not events:
        _LAST_VIRAL_K = 0.0
        return _LAST_VIRAL_K

    per_user_joins: Dict[int, int] = {}
    total_conversions = 0
    for event in events:
        if event.kind == "join":
            per_user_joins[event.referrer_id] = per_user_joins.get(event.referrer_id, 0) + 1
        elif event.kind == "conversion":
            total_conversions += 1

    if not per_user_joins:
        _LAST_VIRAL_K = 0.0
        return _LAST_VIRAL_K

    avg_invites = sum(per_user_joins.values()) / max(len(per_user_joins), 1)
    conversion_rate = 0.0
    total_joins = sum(per_user_joins.values())
    if total_joins:
        conversion_rate = total_conversions / total_joins

    if active_users:
        # normalise invites by active users instead of joiners when available
        avg_invites = total_joins / max(active_users, 1)

    _LAST_VIRAL_K = round(avg_invites * conversion_rate, 4)
    return _LAST_VIRAL_K


def export_prometheus_metrics() -> str:
    """Expose metrics in Prometheus text format for Grafana dashboards."""

    viral_k = _LAST_VIRAL_K
    total_clicks = sum(stats["clicks"] for stats in _USER_STATS.values())
    total_joins = sum(stats["joins"] for stats in _USER_STATS.values())
    total_conversions = sum(stats["conversions"] for stats in _USER_STATS.values())
    lines = [
        "# HELP growth_viral_k Current viral coefficient K",
        "# TYPE growth_viral_k gauge",
        f"growth_viral_k {viral_k}",
        "# HELP growth_referral_clicks_total Total referral clicks recorded",
        "# TYPE growth_referral_clicks_total counter",
        f"growth_referral_clicks_total {total_clicks}",
        "# HELP growth_referral_joins_total Total referral joins recorded",
        "# TYPE growth_referral_joins_total counter",
        f"growth_referral_joins_total {total_joins}",
        "# HELP growth_referral_conversions_total Total referral conversions",
        "# TYPE growth_referral_conversions_total counter",
        f"growth_referral_conversions_total {total_conversions}",
    ]
    return "\n".join(lines) + "\n"


def get_digest_snapshot(*, window: timedelta) -> Dict[str, object]:
    """Return aggregate numbers for the growth digest job."""

    events = list(_iter_events_since(window))
    clicks = sum(1 for e in events if e.kind == "click")
    joins = sum(1 for e in events if e.kind == "join")
    conversions = sum(1 for e in events if e.kind == "conversion")
    channels: Dict[str, int] = {}
    for e in events:
        channels[e.channel] = channels.get(e.channel, 0) + 1
    return {
        "clicks": clicks,
        "joins": joins,
        "conversions": conversions,
        "viral_k": compute_viral_k(window=window),
        "channels": channels,
    }
