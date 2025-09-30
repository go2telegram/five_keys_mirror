from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_DB_PATH_PREFIX = "sqlite"

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


async def init_db() -> None:
    """Ensure database exists and run migrations."""
    if settings.DB_URL.startswith(_DB_PATH_PREFIX):
        # sqlite path like sqlite+aiosqlite:///./var/bot.db
        _, _, path = settings.DB_URL.partition("///")
        if path:
            db_path = Path(path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

    def _upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        root_path = Path(__file__).resolve().parents[2]
        cfg = Config(str(root_path / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", settings.DB_URL)
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)
