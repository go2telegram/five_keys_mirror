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

async_engine = create_async_engine(
    settings.DB_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
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
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
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

    current_rev = await asyncio.to_thread(
        _alembic_upgrade_head_sync, settings.DB_URL
    )
    return current_rev
