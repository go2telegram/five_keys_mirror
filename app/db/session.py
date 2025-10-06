from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

from .base import Base


def _resolve_database_url() -> str:
    url = settings.DATABASE_URL
    if url:
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if "+" not in url and url.startswith("sqlite"):
            return url.replace("sqlite", "sqlite+aiosqlite", 1)
        return url
    return "sqlite+aiosqlite:///./bot.db"


def create_engine() -> AsyncEngine:
    return create_async_engine(_resolve_database_url(), echo=False, future=True)


logger = logging.getLogger(__name__)

engine: AsyncEngine = create_engine()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db_safe(
    *,
    max_attempts: int | None = None,
    initial_delay: float = 1.0,
    max_delay: float = 15.0,
) -> None:
    """Initialize the database, retrying until it becomes available."""

    attempt = 0
    delay = initial_delay

    while True:
        try:
            await init_db()
            return
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            raise
        except Exception as exc:  # noqa: BLE001 - we want to log and retry
            attempt += 1
            await engine.dispose()

            if max_attempts is not None and attempt >= max_attempts:
                logger.exception("Failed to initialize database after %s attempts", attempt)
                raise

            logger.warning(
                "init_db attempt %s failed (%s). Retrying in %.1fs",
                attempt,
                exc,
                delay,
            )

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
