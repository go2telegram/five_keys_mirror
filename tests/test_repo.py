import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import os
import pytest

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_ID", "1")

pytest.importorskip("aiosqlite")

from app.db.models import Base
from app.repo import events, leads, referrals, subscriptions, users


class SessionManager:
    def __init__(self) -> None:
        self._engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
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

    run(_test())


def test_referrals():
    async def _test():
        async with SessionManager() as session:
            await referrals.create(session, referrer_id=10, invited_id=20)
            await session.commit()

            invited, converted = await referrals.stats_for_referrer(session, 10)
            assert invited == 1
            assert converted == 0

            await referrals.convert(session, invited_id=20, bonus_days=3)
            await session.commit()

            invited, converted = await referrals.stats_for_referrer(session, 10)
            assert converted == 1

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
