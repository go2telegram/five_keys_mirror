"""Utilities for growth and attribution analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Order, Subscription, User, UserProfile


@dataclass(slots=True)
class UtmAttributionRow:
    source: str | None
    medium: str | None
    campaign: str | None
    content: str | None
    new_users: int = 0
    quiz: int = 0
    recommendations: int = 0
    subscriptions: int = 0

    def key(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.source, self.medium, self.campaign, self.content)

    def quiz_cr(self) -> float:
        return (self.quiz / self.new_users * 100.0) if self.new_users else 0.0

    def recommendation_cr(self) -> float:
        return (self.recommendations / self.new_users * 100.0) if self.new_users else 0.0

    def subscription_cr(self) -> float:
        return (self.subscriptions / self.new_users * 100.0) if self.new_users else 0.0


@dataclass(slots=True)
class UtmOrderRow:
    source: str | None
    medium: str | None
    campaign: str | None
    content: str | None
    orders: int
    payers: int
    revenue: float


@dataclass(slots=True)
class GrowthReport:
    since: datetime
    until: datetime
    users: list[UtmAttributionRow]
    orders: list[UtmOrderRow]


async def _event_users(
    session: AsyncSession,
    *,
    event_name: str,
    user_ids: Sequence[int],
    since: datetime,
    until: datetime,
) -> set[int]:
    if not user_ids:
        return set()
    stmt: Select = (
        select(distinct(Event.user_id))
        .where(Event.name == event_name, Event.user_id.in_(user_ids))
        .where(Event.ts >= since, Event.ts < until)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result if row[0] is not None}


async def _subscription_users(
    session: AsyncSession,
    *,
    user_ids: Sequence[int],
    since: datetime,
    until: datetime,
) -> set[int]:
    if not user_ids:
        return set()
    stmt = (
        select(distinct(Subscription.user_id))
        .where(Subscription.user_id.in_(user_ids))
        .where(Subscription.since >= since, Subscription.since < until)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result if row[0] is not None}


async def collect_growth_report(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> GrowthReport:
    """Aggregate growth metrics grouped by UTM parameters."""

    until = until or datetime.now(timezone.utc)

    stmt = (
        select(
            User.id,
            UserProfile.utm_source,
            UserProfile.utm_medium,
            UserProfile.utm_campaign,
            UserProfile.utm_content,
        )
        .select_from(User)
        .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
        .where(User.created >= since, User.created < until)
    )
    result = await session.execute(stmt)
    rows = result.all()

    stats_map: dict[tuple[str | None, str | None, str | None, str | None], UtmAttributionRow] = {}
    user_key: dict[int, tuple[str | None, str | None, str | None, str | None]] = {}
    for user_id, source, medium, campaign, content in rows:
        key = (source, medium, campaign, content)
        stats = stats_map.get(key)
        if stats is None:
            stats = UtmAttributionRow(source, medium, campaign, content)
            stats_map[key] = stats
        stats.new_users += 1
        user_key[user_id] = key

    user_ids = list(user_key.keys())

    quiz_users = await _event_users(
        session,
        event_name="quiz_finish",
        user_ids=user_ids,
        since=since,
        until=until,
    )
    for user_id in quiz_users:
        key = user_key.get(user_id)
        if key is None:
            continue
        stats_map[key].quiz += 1

    reco_users = await _event_users(
        session,
        event_name="plan_generated",
        user_ids=user_ids,
        since=since,
        until=until,
    )
    for user_id in reco_users:
        key = user_key.get(user_id)
        if key is None:
            continue
        stats_map[key].recommendations += 1

    sub_users = await _subscription_users(
        session,
        user_ids=user_ids,
        since=since,
        until=until,
    )
    for user_id in sub_users:
        key = user_key.get(user_id)
        if key is None:
            continue
        stats_map[key].subscriptions += 1

    users_rows = sorted(
        stats_map.values(),
        key=lambda row: row.new_users,
        reverse=True,
    )

    source_col = UserProfile.utm_source
    medium_col = UserProfile.utm_medium
    campaign_col = UserProfile.utm_campaign
    content_col = UserProfile.utm_content

    order_stmt = (
        select(
            source_col,
            medium_col,
            campaign_col,
            content_col,
            func.count(Order.id),
            func.count(distinct(Order.user_id)),
            func.coalesce(func.sum(Order.amount), 0.0),
        )
        .select_from(Order)
        .join(User, User.id == Order.user_id)
        .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
        .where(Order.status == "paid", Order.created_at >= since, Order.created_at < until)
        .group_by(source_col, medium_col, campaign_col, content_col)
    )
    order_result = await session.execute(order_stmt)
    order_rows = [
        UtmOrderRow(source, medium, campaign, content, orders, payers, float(revenue or 0.0))
        for source, medium, campaign, content, orders, payers, revenue in order_result.all()
    ]
    order_rows.sort(key=lambda row: row.revenue, reverse=True)

    return GrowthReport(since=since, until=until, users=users_rows, orders=order_rows)


__all__ = ["GrowthReport", "UtmAttributionRow", "UtmOrderRow", "collect_growth_report"]
