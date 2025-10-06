"""Data models and persistence for the revenue engine.

This module implements a light-weight SQLite storage that keeps track of
affiliate offers, clicks, conversions and payouts.  The storage is designed
for a simple single-process bot deployment and therefore uses SQLite from the
standard library instead of a fully fledged async driver.  All helpers use
ISO 8601 timestamps to make analytics and CSV interchange predictable.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from app.config import settings

# Default location for the SQLite database.  The path can be overridden via
# settings (see Settings.REVENUE_DB_PATH).  We ensure the directory exists so
# that the bot can start without any manual preparation.
DB_PATH = Path(getattr(settings, "REVENUE_DB_PATH", "data/revenue.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class Offer:
    external_id: str
    name: str
    campaign: Optional[str]
    default_payout: float


@dataclass(slots=True)
class Click:
    external_id: str
    offer_id: str
    campaign: Optional[str]
    occurred_at: datetime
    cost: float


@dataclass(slots=True)
class Conversion:
    external_id: str
    click_id: str
    occurred_at: datetime
    revenue: float
    status: str


@dataclass(slots=True)
class Payout:
    external_id: str
    conversion_id: str
    occurred_at: datetime
    amount: float


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS offers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id     TEXT NOT NULL UNIQUE,
            name            TEXT NOT NULL,
            campaign        TEXT,
            default_payout  REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS clicks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id     TEXT NOT NULL UNIQUE,
            offer_id        TEXT NOT NULL,
            campaign        TEXT,
            occurred_at     TEXT NOT NULL,
            cost            REAL DEFAULT 0,
            FOREIGN KEY(offer_id) REFERENCES offers(external_id)
        );

        CREATE TABLE IF NOT EXISTS conversions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id     TEXT NOT NULL UNIQUE,
            click_id        TEXT NOT NULL,
            occurred_at     TEXT NOT NULL,
            revenue         REAL DEFAULT 0,
            status          TEXT DEFAULT 'approved',
            FOREIGN KEY(click_id) REFERENCES clicks(external_id)
        );

        CREATE TABLE IF NOT EXISTS payouts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id     TEXT NOT NULL UNIQUE,
            conversion_id   TEXT NOT NULL,
            occurred_at     TEXT NOT NULL,
            amount          REAL NOT NULL,
            FOREIGN KEY(conversion_id) REFERENCES conversions(external_id)
        );

        CREATE INDEX IF NOT EXISTS idx_clicks_campaign ON clicks(campaign);
        CREATE INDEX IF NOT EXISTS idx_conversions_click_id ON conversions(click_id);
        CREATE INDEX IF NOT EXISTS idx_payouts_conversion_id ON payouts(conversion_id);
        """
    )


def init_db() -> None:
    """Initialise the SQLite schema if it does not exist yet."""
    with _connect() as conn:
        _ensure_schema(conn)


def _iso(value: datetime | str | None) -> str:
    if not value:
        return datetime.utcnow().isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def register_offer(data: Offer | dict) -> None:
    payload = data if isinstance(data, dict) else data.__dict__
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO offers(external_id, name, campaign, default_payout)
            VALUES(:external_id, :name, :campaign, :default_payout)
            ON CONFLICT(external_id) DO UPDATE SET
                name=excluded.name,
                campaign=excluded.campaign,
                default_payout=excluded.default_payout
            """,
            {
                "external_id": payload["external_id"],
                "name": payload["name"],
                "campaign": payload.get("campaign"),
                "default_payout": float(payload.get("default_payout", 0) or 0),
            },
        )


def register_click(data: Click | dict) -> None:
    payload = data if isinstance(data, dict) else data.__dict__
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO clicks(external_id, offer_id, campaign, occurred_at, cost)
            VALUES(:external_id, :offer_id, :campaign, :occurred_at, :cost)
            ON CONFLICT(external_id) DO UPDATE SET
                offer_id=excluded.offer_id,
                campaign=excluded.campaign,
                occurred_at=excluded.occurred_at,
                cost=excluded.cost
            """,
            {
                "external_id": payload["external_id"],
                "offer_id": payload["offer_id"],
                "campaign": payload.get("campaign"),
                "occurred_at": _iso(payload.get("occurred_at")),
                "cost": float(payload.get("cost", 0) or 0),
            },
        )


def register_conversion(data: Conversion | dict) -> None:
    payload = data if isinstance(data, dict) else data.__dict__
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO conversions(external_id, click_id, occurred_at, revenue, status)
            VALUES(:external_id, :click_id, :occurred_at, :revenue, :status)
            ON CONFLICT(external_id) DO UPDATE SET
                click_id=excluded.click_id,
                occurred_at=excluded.occurred_at,
                revenue=excluded.revenue,
                status=excluded.status
            """,
            {
                "external_id": payload["external_id"],
                "click_id": payload["click_id"],
                "occurred_at": _iso(payload.get("occurred_at")),
                "revenue": float(payload.get("revenue", 0) or 0),
                "status": payload.get("status", "approved"),
            },
        )


def register_payout(data: Payout | dict) -> None:
    payload = data if isinstance(data, dict) else data.__dict__
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO payouts(external_id, conversion_id, occurred_at, amount)
            VALUES(:external_id, :conversion_id, :occurred_at, :amount)
            ON CONFLICT(external_id) DO UPDATE SET
                conversion_id=excluded.conversion_id,
                occurred_at=excluded.occurred_at,
                amount=excluded.amount
            """,
            {
                "external_id": payload["external_id"],
                "conversion_id": payload["conversion_id"],
                "occurred_at": _iso(payload.get("occurred_at")),
                "amount": float(payload.get("amount", 0) or 0),
            },
        )


def get_revenue_summary(days: int = 30) -> dict:
    """Return aggregated KPI metrics for the revenue dashboard."""
    init_db()
    with _connect() as conn:
        totals = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM offers)          AS offers,
                (SELECT COUNT(*) FROM clicks)          AS clicks,
                (SELECT COUNT(*) FROM conversions)     AS conversions,
                (SELECT COUNT(*) FROM payouts)         AS payouts,
                (SELECT IFNULL(SUM(cost), 0) FROM clicks) AS spend,
                (
                    SELECT IFNULL(SUM(amount), 0) FROM payouts
                ) AS revenue
        """
        ).fetchone()

        cost = float(totals["spend"] or 0)
        revenue = float(totals["revenue"] or 0)
        roi = ((revenue - cost) / cost) if cost else None
        epc = (revenue / totals["clicks"]) if totals["clicks"] else 0.0

        cost_by_campaign = {
            row["campaign"] or "—": float(row["spend"] or 0)
            for row in conn.execute(
                "SELECT campaign, SUM(cost) AS spend FROM clicks GROUP BY campaign"
            )
        }
        revenue_by_campaign = {
            row["campaign"] or "—": float(row["revenue"] or 0)
            for row in conn.execute(
                """
                SELECT clicks.campaign AS campaign, SUM(payouts.amount) AS revenue
                FROM payouts
                JOIN conversions ON payouts.conversion_id = conversions.external_id
                JOIN clicks ON conversions.click_id = clicks.external_id
                GROUP BY clicks.campaign
                """
            )
        }

        roi_per_campaign: list[dict] = []
        for campaign in sorted({*cost_by_campaign.keys(), *revenue_by_campaign.keys()}):
            spend = cost_by_campaign.get(campaign, 0.0)
            rev = revenue_by_campaign.get(campaign, 0.0)
            roi_value = ((rev - spend) / spend) if spend else None
            roi_per_campaign.append(
                {
                    "campaign": campaign,
                    "spend": spend,
                    "revenue": rev,
                    "roi": roi_value,
                }
            )

        trends = get_daily_trends(conn=conn, days=days)

    return {
        "totals": {
            "offers": totals["offers"],
            "clicks": totals["clicks"],
            "conversions": totals["conversions"],
            "payouts": totals["payouts"],
            "revenue": revenue,
            "spend": cost,
            "roi": roi,
            "epc": epc,
        },
        "roi_per_campaign": roi_per_campaign,
        "trends": trends,
    }


def get_daily_trends(*, conn: sqlite3.Connection | None = None, days: int = 30) -> list[dict]:
    """Return daily revenue, spend and conversion counts for Grafana widgets."""
    close_conn = False
    conn_ctx = None
    if conn is None:
        close_conn = True
        conn_ctx = _connect()
        conn = conn_ctx.__enter__()
    try:
        clicks_daily = {
            row["day"]: {
                "clicks": row["clicks"],
                "spend": float(row["spend"] or 0),
            }
            for row in conn.execute(
                """
                SELECT substr(occurred_at, 1, 10) AS day,
                       COUNT(*) AS clicks,
                       SUM(cost) AS spend
                FROM clicks
                GROUP BY day
                ORDER BY day DESC
                LIMIT ?
                """,
                (days,),
            )
        }
        conversions_daily = {
            row["day"]: {
                "conversions": row["conversions"],
                "revenue": float(row["revenue"] or 0),
            }
            for row in conn.execute(
                """
                SELECT substr(conversions.occurred_at, 1, 10) AS day,
                       COUNT(*) AS conversions,
                       SUM(payouts.amount) AS revenue
                FROM conversions
                LEFT JOIN payouts ON payouts.conversion_id = conversions.external_id
                GROUP BY day
                ORDER BY day DESC
                LIMIT ?
                """,
                (days,),
            )
        }
        payouts_daily = {
            row["day"]: float(row["revenue"] or 0)
            for row in conn.execute(
                """
                SELECT substr(occurred_at, 1, 10) AS day,
                       SUM(amount) AS revenue
                FROM payouts
                GROUP BY day
                ORDER BY day DESC
                LIMIT ?
                """,
                (days,),
            )
        }

        all_days = sorted({*clicks_daily.keys(), *conversions_daily.keys(), *payouts_daily.keys()}, reverse=True)
        trend = []
        for day in all_days:
            trend.append(
                {
                    "day": day,
                    "clicks": clicks_daily.get(day, {}).get("clicks", 0),
                    "conversions": conversions_daily.get(day, {}).get("conversions", 0),
                    "revenue": conversions_daily.get(day, {}).get("revenue", 0.0),
                    "payout_revenue": payouts_daily.get(day, 0.0),
                    "spend": clicks_daily.get(day, {}).get("spend", 0.0),
                }
            )
        return trend
    finally:
        if close_conn and conn_ctx is not None:
            conn_ctx.__exit__(None, None, None)


__all__ = [
    "Offer",
    "Click",
    "Conversion",
    "Payout",
    "init_db",
    "register_offer",
    "register_click",
    "register_conversion",
    "register_payout",
    "get_revenue_summary",
    "get_daily_trends",
]
