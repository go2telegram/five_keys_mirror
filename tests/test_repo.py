import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.repo import events, leads, referrals, subscriptions, users
from app.services.daily_tip import compute_next_fire

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("ADMIN_USER_IDS", "1,2")

pytest.importorskip("aiosqlite")


class SessionManager:
    def __init__(self) -> None:
        self._engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)
        self._session = None

    async def __aenter__(self) -> AsyncSession:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._session = self._sessionmaker()
        return await self._session.__aenter__()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
        await self._engine.dispose()


def run(coro):
    return asyncio.run(coro)


def test_user_get_or_create():
    async def _test():
        async with SessionManager() as session:
            user = await users.get_or_create_user(session, 123, "demo")
            await session.commit()
            assert user.id == 123
            assert user.username == "demo"

            user2 = await users.get_or_create_user(session, 123, "demo_updated")
            await session.commit()
            assert user2.username == "demo_updated"

    run(_test())


def test_subscriptions_set_plan():
    async def _test():
        async with SessionManager() as session:
            await users.get_or_create_user(session, 1, "user1")
            await subscriptions.set_plan(session, 1, "basic", days=7)
            await session.commit()

            is_active, current = await subscriptions.is_active(session, 1)
            assert is_active
            assert current.plan == "basic"

            future = datetime.now(timezone.utc) + timedelta(days=30)
            await subscriptions.set_plan(session, 1, "pro", until=future)
            await session.commit()

            is_active, current = await subscriptions.is_active(session, 1)
            assert current.plan == "pro"
            assert abs((current.until - future).total_seconds()) < 1

            await subscriptions.set_plan(session, 1, "pro", days=5)
            await session.commit()

            _, extended = await subscriptions.is_active(session, 1)
            assert extended.until >= future

            await subscriptions.delete(session, 1)
            await session.commit()

            assert await subscriptions.get(session, 1) is None

    run(_test())


def test_referrals():
    async def _test():
        async with SessionManager() as session:
            await referrals.create(session, referrer_id=10, invited_id=20)
            await referrals.create(session, referrer_id=10, invited_id=21)
            await session.commit()

            invited, converted = await referrals.stats_for_referrer(session, 10)
            assert invited == 2
            assert converted == 0

            await referrals.convert(session, invited_id=20, bonus_days=3)
            await session.commit()

            invited, converted = await referrals.stats_for_referrer(session, 10)
            assert converted == 1

            listed = await referrals.list_for(session, 10, limit=20, offset=0, period="all")
            assert len(listed) == 2
            assert {item.invited_id for item in listed} == {20, 21}

            count_7d = await referrals.count_for(session, 10, period="7d")
            assert count_7d == 2

    run(_test())


def test_users_find():
    async def _test():
        async with SessionManager() as session:
            await users.get_or_create_user(session, 1, "alpha")
            await users.get_or_create_user(session, 2, "beta")
            await users.get_or_create_user(session, 3, "gamma")
            await session.commit()

            total = await users.count(session)
            assert total == 3

            subset = await users.find(session, "bet", limit=20, offset=0)
            assert len(subset) == 1
            assert subset[0].id == 2

            direct = await users.find(session, "3", limit=20, offset=0)
            assert len(direct) == 1
            assert direct[0].id == 3

            counted = await users.count(session, "alp")
            assert counted == 1

    run(_test())


def test_leads():
    async def _test():
        async with SessionManager() as session:
            await leads.add(session, 50, "user50", "Name", "+7000", "comment")
            await leads.add(session, 51, "user51", "Name2", "+7111", "")
            await session.commit()

            assert await leads.count(session) == 2
            last = await leads.list_last(session, 1)
            assert len(last) == 1
            assert last[0].user_id == 51

    run(_test())


def test_events_notify():
    async def _test():
        async with SessionManager() as session:
            await events.log(session, 1, "notify_on", {})
            await events.log(session, 2, "notify_on", {})
            await events.log(session, 2, "notify_off", {})
            await session.commit()

            recipients = await events.notify_recipients(session)
            assert 1 in recipients
            assert 2 not in recipients

    run(_test())


def test_user_utm_persistence():
    async def _test():
        async with SessionManager() as session:
            await users.get_or_create_user(
                session,
                101,
                "utm",
                utm={"utm_source": "tiktok", "utm_medium": "ads"},
            )
            await session.commit()

            record = await users.get_user(session, 101)
            assert record.utm_source == "tiktok"
            assert record.utm_medium == "ads"

            await users.get_or_create_user(
                session,
                101,
                "utm",
                utm={"utm_source": "instagram"},
            )
            await session.commit()
            record = await users.get_user(session, 101)
            # сохраняем исходный источник
            assert record.utm_source == "tiktok"

            await users.set_utm(session, 101, {"utm_campaign": "launch"})
            await session.commit()
            record = await users.get_user(session, 101)
            assert record.utm_campaign == "launch"

            await users.set_utm(
                session,
                101,
                {"utm_source": "stories"},
                overwrite=True,
            )
            await session.commit()
            record = await users.get_user(session, 101)
            assert record.utm_source == "stories"

    run(_test())


def test_daily_tip_schedule_calculation():
    base = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)
    fire = compute_next_fire(timezone="Europe/Moscow", now=base)
    local = fire.astimezone(timezone.utc)
    # 6 UTC -> 9 MSK, значит рассылка должна быть в тот же день 7 UTC (10 MSK)
    assert local.hour == 7

    after = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    next_fire = compute_next_fire(timezone="Europe/Moscow", now=after)
    assert next_fire > after
    assert next_fire.astimezone(timezone.utc).hour == 7
    assert next_fire.date() > after.date()


def test_growth_metrics_summary():
    async def _test():
        async with SessionManager() as session:
            await users.get_or_create_user(
                session,
                201,
                "user1",
                utm={
                    "utm_source": "tiktok",
                    "utm_medium": "ads",
                    "utm_campaign": "spring",
                },
            )
            await users.get_or_create_user(
                session,
                202,
                "user2",
                utm={
                    "utm_source": "tiktok",
                    "utm_medium": "ads",
                    "utm_campaign": "spring",
                },
            )
            await users.get_or_create_user(
                session,
                203,
                "user3",
                utm={
                    "utm_source": "instagram",
                    "utm_medium": "stories",
                    "utm_campaign": "summer",
                },
            )
            await subscriptions.set_plan(session, 201, "basic", days=7)
            await session.commit()

            summary = await users.utm_summary(session)
            assert any(row["premium"] == 1 for row in summary if row["utm_source"] == "tiktok")

            await events.log(session, 201, "premium_cta_show", {"source": "growth_drop"})
            await events.log(session, 201, "premium_cta_click", {"source": "growth_drop"})
            await events.log(session, 202, "premium_cta_show", {"source": "growth_drop"})
            await session.commit()

            exposures = await events.count_by_meta(
                session,
                "premium_cta_show",
                meta_filters={"source": "growth_drop"},
            )
            clicks = await events.count_by_meta(
                session,
                "premium_cta_click",
                meta_filters={"source": "growth_drop"},
            )
            assert exposures == 2
            assert clicks == 1

    run(_test())
