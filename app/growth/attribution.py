"""Utilities for UTM attribution and growth analytics."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote_plus, unquote_plus, urlencode

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Subscription, UserProfile

UTM_KEYS: tuple[str, ...] = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
UtmKey = tuple[str, str, str, str]


@dataclass(slots=True)
class UtmFunnelMetrics:
    """Aggregated funnel metrics for a single UTM bucket."""

    registrations: int = 0
    quiz_starts: int = 0
    recommendations: int = 0
    premium_buys: int = 0

    @property
    def quiz_ctr(self) -> float:
        return (self.quiz_starts / self.registrations * 100.0) if self.registrations else 0.0

    @property
    def recommendation_rate(self) -> float:
        return (self.recommendations / self.registrations * 100.0) if self.registrations else 0.0

    @property
    def premium_cr(self) -> float:
        return (self.premium_buys / self.registrations * 100.0) if self.registrations else 0.0


def parse_utm_payload(payload: str) -> dict[str, str]:
    """Extract UTM parameters from a Telegram /start payload."""

    if not payload:
        return {}

    decoded = unquote_plus(payload.strip())
    if "&" not in decoded and " " in decoded:
        decoded = decoded.replace(" ", "&")

    sanitized: dict[str, str] = {}
    for key, value in parse_qsl(decoded, keep_blank_values=False):
        key = key.strip().lower()
        if key not in UTM_KEYS:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        sanitized[key] = cleaned[:128]
    return sanitized


def normalize_utm(utm: Mapping[str, str]) -> dict[str, str]:
    """Return UTM dict limited to known keys with trimmed values."""

    normalized: dict[str, str] = {}
    for key in UTM_KEYS:
        value = utm.get(key)
        if not value:
            continue
        normalized[key] = str(value).strip()[:128]
    return normalized


def build_start_payload(utm: Mapping[str, str]) -> tuple[str, str]:
    """Return raw payload and encoded query fragment for a deeplink."""

    filtered = normalize_utm(utm)
    if not filtered:
        return "", ""
    raw_payload = urlencode(filtered)
    encoded = quote_plus(raw_payload)
    return raw_payload, encoded


def format_utm_label(key: UtmKey) -> str:
    """Return a human-readable label for a UTM key tuple."""

    parts = [part if part else "—" for part in key]
    if all(part == "—" for part in parts):
        return "unknown"
    source, medium, campaign, content = parts
    return " · ".join([source, medium, campaign, content])


def _key_from_payload(utm: Mapping[str, object] | None) -> UtmKey | None:
    if not utm:
        return None
    values: list[str] = []
    has_value = False
    for key in UTM_KEYS:
        raw = utm.get(key) if isinstance(utm, Mapping) else None
        if isinstance(raw, str):
            cleaned = raw.strip()
        elif raw is None:
            cleaned = ""
        else:
            cleaned = str(raw).strip()
        if cleaned:
            has_value = True
            values.append(cleaned[:128])
        else:
            values.append("—")
    if not has_value:
        return None
    return tuple(values)  # type: ignore[return-value]


async def _load_utm_map(session: AsyncSession) -> dict[int, UtmKey]:
    stmt = select(UserProfile.user_id, UserProfile.utm).where(UserProfile.utm.is_not(None))
    result = await session.execute(stmt)
    mapping: dict[int, UtmKey] = {}
    for user_id, payload in result.all():
        key = _key_from_payload(payload)
        if key is None:
            continue
        mapping[int(user_id)] = key
    return mapping


async def collect_funnel_metrics(session: AsyncSession) -> dict[UtmKey, UtmFunnelMetrics]:
    """Aggregate registrations and key actions by UTM."""

    utm_map = await _load_utm_map(session)
    metrics: dict[UtmKey, UtmFunnelMetrics] = defaultdict(UtmFunnelMetrics)
    if not utm_map:
        return {}

    for key in utm_map.values():
        metrics[key].registrations += 1

    user_ids = list(utm_map.keys())

    quiz_stmt = (
        select(distinct(Event.user_id))
        .where(Event.name == "quiz_start", Event.user_id.in_(user_ids))
        .where(Event.user_id.is_not(None))
    )
    quiz_users = (await session.execute(quiz_stmt)).scalars().all()
    for user_id in quiz_users:
        key = utm_map.get(int(user_id))
        if key is not None:
            metrics[key].quiz_starts += 1

    recommend_stmt = (
        select(distinct(Event.user_id))
        .where(Event.name == "plan_generated", Event.user_id.in_(user_ids))
        .where(Event.user_id.is_not(None))
    )
    recommend_users = (await session.execute(recommend_stmt)).scalars().all()
    for user_id in recommend_users:
        key = utm_map.get(int(user_id))
        if key is not None:
            metrics[key].recommendations += 1

    premium_stmt = select(Subscription.user_id).where(Subscription.user_id.in_(user_ids))
    premium_users = (await session.execute(premium_stmt)).scalars().all()
    for user_id in premium_users:
        key = utm_map.get(int(user_id))
        if key is not None:
            metrics[key].premium_buys += 1

    return metrics


def summarize(metrics: Mapping[UtmKey, UtmFunnelMetrics]) -> UtmFunnelMetrics:
    total = UtmFunnelMetrics()
    for item in metrics.values():
        total.registrations += item.registrations
        total.quiz_starts += item.quiz_starts
        total.recommendations += item.recommendations
        total.premium_buys += item.premium_buys
    return total


def sort_metrics(
    metrics: Mapping[UtmKey, UtmFunnelMetrics], *, limit: int | None = None
) -> list[tuple[UtmKey, UtmFunnelMetrics]]:
    ordered = sorted(
        metrics.items(), key=lambda item: item[1].registrations, reverse=True
    )
    if limit is None:
        return ordered
    return ordered[:limit]
