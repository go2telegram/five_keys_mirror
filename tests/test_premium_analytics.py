from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base, Event, Subscription
from app.services.premium_analytics import collect_premium_report


pytest.importorskip("aiosqlite")


@pytest.mark.asyncio
async def test_collect_premium_report(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        session.add_all(
            [
                Subscription(user_id=1, plan="basic", since=now - timedelta(days=10), until=now + timedelta(days=20)),
                Subscription(user_id=2, plan="basic", since=now - timedelta(days=5), until=now + timedelta(days=15)),
                Subscription(user_id=3, plan="pro", since=now - timedelta(days=3), until=now + timedelta(days=45)),
                Subscription(user_id=4, plan="pro", since=now - timedelta(days=40), until=now - timedelta(days=1)),
            ]
        )
        session.add_all(
            [
                Event(user_id=1, name="cta_premium_shown", meta={}, ts=now - timedelta(days=2)),
                Event(user_id=1, name="cta_premium_shown", meta={}, ts=now - timedelta(days=1, hours=3)),
                Event(user_id=2, name="cta_premium_shown", meta={}, ts=now - timedelta(hours=12)),
                Event(user_id=3, name="cta_premium_shown", meta={}, ts=now - timedelta(hours=2)),
                Event(user_id=1, name="cta_premium_clicked", meta={}, ts=now - timedelta(days=1)),
                Event(user_id=2, name="cta_premium_clicked", meta={}, ts=now - timedelta(hours=1)),
                Event(user_id=1, name="buy_started", meta={}, ts=now - timedelta(days=1)),
                Event(user_id=2, name="buy_started", meta={}, ts=now - timedelta(hours=5)),
                Event(user_id=3, name="buy_started", meta={}, ts=now - timedelta(days=3)),
                Event(user_id=3, name="buy_success", meta={}, ts=now - timedelta(hours=3)),
                Event(user_id=4, name="buy_success", meta={}, ts=now - timedelta(days=5)),
                Event(user_id=2, name="subscription_cancelled", meta={}, ts=now - timedelta(days=10)),
                Event(user_id=2, name="subscription_cancelled", meta={}, ts=now - timedelta(days=45)),
            ]
        )
        await session.commit()

    monkeypatch.setattr(settings, "SUB_BASIC_PRICE", "299")
    monkeypatch.setattr(settings, "SUB_PRO_PRICE", "599")

    async with session_factory() as session:
        report = await collect_premium_report(session)

    assert report.active_subscriptions == 3
    assert report.plan_breakdown == {"basic": 2, "pro": 1}
    assert float(report.mrr) == pytest.approx(1197.0)
    assert float(report.arppu) == pytest.approx(399.0)
    assert report.new_subscriptions_day == 1
    assert report.churn_events_30d == 1
    assert report.churn_rate == pytest.approx(33.33, rel=1e-2, abs=1e-2)
    assert report.events == {
        "cta_premium_shown": 4,
        "cta_premium_clicked": 2,
        "buy_started": 3,
        "buy_success": 2,
    }
    assert report.ctr_cta == pytest.approx(50.0)

    await engine.dispose()
