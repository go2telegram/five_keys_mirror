import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Event
from app.repo import events, leads, referrals, subscriptions, users

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
            first = await referrals.upsert_referral(session, referrer_id=10, invited_id=20)
            duplicate = await referrals.upsert_referral(session, referrer_id=10, invited_id=20)
            assert first.id == duplicate.id

            await referrals.upsert_referral(session, referrer_id=10, invited_id=21)
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


def test_events_upsert_idempotent():
    async def _test():
        async with SessionManager() as session:
            created = await events.upsert(session, 1, "notify_on", {"status": "on"})
            await session.commit()

            updated = await events.upsert(session, 1, "notify_on", {"status": "still_on"})
            await session.commit()

            assert created.id == updated.id

            total_stmt = select(func.count(Event.id))
            total = await session.execute(total_stmt)
            assert total.scalar_one() == 1

            latest = await events.last_by(session, 1, "notify_on")
            assert latest is not None
            assert latest.meta == {"status": "still_on"}

    run(_test())
