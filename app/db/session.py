from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_DB_PATH_PREFIX = "sqlite"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_ENGINE_IMPORT_ERROR: Exception | None = None

try:
    async_engine = create_async_engine(
        settings.DB_URL,
        echo=False,
        pool_pre_ping=True,
    )
except ModuleNotFoundError as exc:
    if "aiosqlite" in str(exc):
        async_engine = None  # type: ignore[assignment]
        _ENGINE_IMPORT_ERROR = exc
    else:  # pragma: no cover - re-raise unrelated import errors
        raise

if async_engine is not None:
    async_session_factory = async_sessionmaker(
        async_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
else:  # pragma: no cover - triggered only when driver missing
    async_session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    if async_session_factory is None:
        raise RuntimeError(
            "aiosqlite driver is not installed; install aiosqlite to use database features",
        ) from _ENGINE_IMPORT_ERROR
    async with async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    if async_session_factory is None:
        raise RuntimeError(
            "aiosqlite driver is not installed; install aiosqlite to use database features",
        ) from _ENGINE_IMPORT_ERROR
    async with async_session_factory() as session:
        yield session


def _alembic_upgrade_head_sync(db_url: str) -> str | None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    sync_url = db_url.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    finally:
        engine.dispose()


async def init_db() -> str | None:
    """Ensure database exists and run migrations."""
    if settings.DB_URL.startswith(_DB_PATH_PREFIX):
        # sqlite path like sqlite+aiosqlite:///./var/bot.db
        _, _, path = settings.DB_URL.partition("///")
        if path:
            db_path = Path(path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

    current_rev = await asyncio.to_thread(_alembic_upgrade_head_sync, settings.DB_URL)
    return current_rev
