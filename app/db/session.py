from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_IMPORT_ERROR: Exception | None = None
_SYNC_DRIVER_REPLACEMENTS = ("+aiosqlite", "+asyncpg")

log = logging.getLogger("db")


def _strip_driver(db_url: str) -> str:
    stripped = db_url
    for suffix in _SYNC_DRIVER_REPLACEMENTS:
        stripped = stripped.replace(suffix, "")
    return stripped


def _ensure_sqlite_dir(db_url: str) -> None:
    if not db_url.startswith("sqlite"):
        return
    _, _, raw_path = db_url.partition("///")
    if not raw_path:
        return
    db_path = Path(raw_path)
    directory = db_path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log.info("DB: ensured sqlite dir %s", directory)
    except Exception:
        log.exception("DB: ensure sqlite dir failed")


def _fetch_revision_sync(db_url: str) -> str | None:
    engine = create_engine(_strip_driver(db_url), future=True)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    finally:
        engine.dispose()


def _alembic_upgrade_head_sync(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


try:
    async_engine = create_async_engine(
        settings.DB_URL,
        echo=False,
        pool_pre_ping=True,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - driver missing only in CI sandbox
    if "aiosqlite" in str(exc):
        async_engine = None  # type: ignore[assignment]
        _ENGINE_IMPORT_ERROR = exc
        log.warning("DB: async driver aiosqlite is not available; async features disabled")
    else:
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


async def current_revision(db_url: str | None = None) -> str | None:
    url = db_url or settings.DB_URL
    try:
        return await asyncio.to_thread(_fetch_revision_sync, url)
    except Exception:
        log.exception("DB: get current revision failed")
        return None


async def init_db(engine: AsyncEngine | None = None) -> str | None:
    """Apply migrations with timeout and never block startup."""

    db_url = settings.DB_URL
    log.info("DB: url=%s migrate_on_start=%s", db_url, settings.DB_MIGRATE_ON_START)

    _ensure_sqlite_dir(db_url)

    engine = engine or async_engine
    if engine is not None:
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SELECT 1"))
            log.info("DB: connectivity ok")
        except Exception:
            log.exception("DB: connectivity check failed")
    else:
        log.warning("DB: async engine unavailable; skipping connectivity check")

    if not settings.DB_MIGRATE_ON_START:
        log.warning("DB: migrations skipped by flag")
        revision = await current_revision(db_url)
        log.info("DB: current revision=%s", revision or "unknown")
        return revision

    try:
        log.info("DB: alembic upgrade head — start")
        await asyncio.wait_for(
            asyncio.to_thread(_alembic_upgrade_head_sync, db_url),
            timeout=15.0,
        )
        log.info("DB: alembic upgrade head — done")
    except asyncio.TimeoutError:
        log.error("DB: migration timeout, continue without blocking startup")
    except Exception:
        log.exception("DB: migration failed, continue without blocking startup")

    revision = await current_revision(db_url)
    log.info("DB: current revision=%s", revision or "unknown")
    return revision
