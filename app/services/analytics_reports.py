"""Utilities to assemble analytics reports for admin commands."""

from __future__ import annotations

import csv
import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CommerceSubscription, Event, User
from app.repo import events as events_repo

LOG = logging.getLogger("analytics")
EXPORT_DIR = Path("var/exports")


@dataclass(slots=True)
class FunnelStats:
    shows: int = 0
    clicks: int = 0
    buy_started: int = 0
    buy_success: int = 0

    def ctr(self) -> float:
        return self.clicks / self.shows if self.shows else 0.0

    def checkout_rate(self) -> float:
        return self.buy_success / self.buy_started if self.buy_started else 0.0


@dataclass(slots=True)
class CohortRow:
    week_start: dt.date
    new_users: int
    conversions: int

    def conversion_rate(self) -> float:
        return self.conversions / self.new_users if self.new_users else 0.0


@dataclass(slots=True)
class CTRRow:
    source: str
    shows: int
    clicks: int

    def rate(self) -> float:
        return self.clicks / self.shows if self.shows else 0.0


def _ensure_export_dir(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        LOG.warning("analytics export dir inaccessible: %s", directory, exc_info=True)
        return False


def export_csv(filename: str, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> Path | None:
    """Write a CSV snapshot under :mod:`var/exports` and return the path."""

    if not _ensure_export_dir(EXPORT_DIR):
        return None

    path = EXPORT_DIR / filename
    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(list(headers))
            for row in rows:
                writer.writerow(list(row))
    except PermissionError:
        LOG.warning("failed to write analytics CSV %s", path, exc_info=True)
        return None
    return path


async def gather_funnel(session: AsyncSession, *, days: int = 30) -> FunnelStats:
    """Collect funnel counters for the Premium upsell."""

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    shows = await events_repo.stats(session, name="premium_info_open", since=since)
    clicks = await events_repo.stats(session, name="premium_cta_click", since=since)
    buy_started = await events_repo.stats(session, name="premium_buy_open", since=since)

    stmt = select(CommerceSubscription).where(CommerceSubscription.started_at >= since)
    result = await session.execute(stmt)
    success = sum(1 for _ in result.scalars())

    return FunnelStats(shows=shows, clicks=clicks, buy_started=buy_started, buy_success=success)


def format_funnel(stats: FunnelStats, *, days: int = 30) -> str:
    lines = [f"🔄 Premium funnel за {days} дн."]
    lines.append(f"Показы: {stats.shows}")
    lines.append(f"Клики: {stats.clicks} (CTR {stats.ctr():.1%})")
    lines.append(f"Начали оплату: {stats.buy_started}")
    lines.append(f"Покупки: {stats.buy_success} (конверсия {stats.checkout_rate():.1%})")
    return "\n".join(lines)


async def gather_cohorts(session: AsyncSession, *, weeks: int = 6) -> list[CohortRow]:
    """Return cohort rows grouped by user registration week."""

    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(weeks=weeks)

    users_stmt = select(User).where(User.created >= window_start)
    users_result = await session.execute(users_stmt)
    users = list(users_result.scalars())

    subs_stmt = select(CommerceSubscription).where(CommerceSubscription.started_at >= window_start)
    subs_result = await session.execute(subs_stmt)
    subscriptions = list(subs_result.scalars())

    return aggregate_cohorts(users, subscriptions, weeks=weeks)


def aggregate_cohorts(
    users: Iterable[User],
    subscriptions: Iterable[CommerceSubscription],
    *,
    weeks: int = 6,
) -> list[CohortRow]:
    cohorts: dict[dt.date, CohortRow] = {}
    cohort_lookup: dict[int, dt.date] = {}

    for user in users:
        created = user.created
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        week_start = created.date() - dt.timedelta(days=created.weekday())
        row = cohorts.setdefault(week_start, CohortRow(week_start=week_start, new_users=0, conversions=0))
        row.new_users += 1
        cohort_lookup[user.id] = week_start

    for sub in subscriptions:
        if sub.user_id is None:
            continue
        week_start = cohort_lookup.get(sub.user_id)
        if week_start is None:
            continue
        cohorts[week_start].conversions += 1

    ordered = sorted(cohorts.values(), key=lambda row: row.week_start, reverse=True)
    if weeks > 0:
        ordered = ordered[:weeks]
    return ordered


def format_cohorts(rows: Sequence[CohortRow]) -> str:
    if not rows:
        return "📈 Cohort report: данных нет"

    lines = ["📈 Cohort report по неделям"]
    for row in rows:
        lines.append(
            (
                f"{row.week_start:%d.%m}: новых {row.new_users}, оплат {row.conversions}, "
                f"конверсия {row.conversion_rate():.1%}"
            )
        )
    return "\n".join(lines)


async def gather_ctr(session: AsyncSession, *, days: int = 30) -> list[CTRRow]:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    stmt = select(Event).where(Event.name.in_(["premium_cta_click", "premium_info_open"]))
    stmt = stmt.where(Event.ts >= since)
    result = await session.execute(stmt)
    events = list(result.scalars())
    return aggregate_ctr(events)


def aggregate_ctr(events: Iterable[Event]) -> list[CTRRow]:
    shows: defaultdict[str, int] = defaultdict(int)
    clicks: defaultdict[str, int] = defaultdict(int)

    for event in events:
        meta = event.meta if isinstance(event.meta, dict) else {}
        source = str(meta.get("source") or "unknown")
        if event.name == "premium_cta_click":
            clicks[source] += 1
        elif event.name == "premium_info_open" and source.startswith("cta:"):
            base = source.split("cta:", 1)[-1] or "cta"
            shows[base] += 1

    rows: list[CTRRow] = []
    for key in sorted(set(list(shows) + list(clicks))):
        rows.append(CTRRow(source=key, shows=shows.get(key, 0), clicks=clicks.get(key, 0)))
    return rows


def format_ctr(rows: Sequence[CTRRow], *, days: int = 30) -> str:
    if not rows:
        return "🎯 CTR отчёт: событий не найдено"

    lines = [f"🎯 CTR по источникам за {days} дн."]
    for row in rows:
        lines.append(f"{row.source}: {row.clicks}/{row.shows} (CTR {row.rate():.1%})")
    return "\n".join(lines)


def export_funnel_csv(stats: FunnelStats) -> Path | None:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = [
        ("shows", stats.shows),
        ("clicks", stats.clicks),
        ("buy_started", stats.buy_started),
        ("buy_success", stats.buy_success),
        ("ctr", f"{stats.ctr():.4f}"),
        ("checkout_rate", f"{stats.checkout_rate():.4f}"),
    ]
    return export_csv(f"funnel_{timestamp}.csv", ["metric", "value"], rows)


def export_cohort_csv(rows: Sequence[CohortRow]) -> Path | None:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_rows = [
        (
            row.week_start.isoformat(),
            row.new_users,
            row.conversions,
            f"{row.conversion_rate():.4f}",
        )
        for row in rows
    ]
    return export_csv("cohorts_" + timestamp + ".csv", ["week", "new_users", "conversions", "rate"], csv_rows)


def export_ctr_csv(rows: Sequence[CTRRow]) -> Path | None:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_rows = [
        (
            row.source,
            row.shows,
            row.clicks,
            f"{row.rate():.4f}",
        )
        for row in rows
    ]
    return export_csv("ctr_" + timestamp + ".csv", ["source", "shows", "clicks", "rate"], csv_rows)


__all__ = [
    "FunnelStats",
    "CohortRow",
    "CTRRow",
    "aggregate_cohorts",
    "aggregate_ctr",
    "export_csv",
    "export_cohort_csv",
    "export_ctr_csv",
    "export_funnel_csv",
    "format_cohorts",
    "format_ctr",
    "format_funnel",
    "gather_cohorts",
    "gather_ctr",
    "gather_funnel",
]
