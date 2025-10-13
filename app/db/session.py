from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        engine.dispose()


def _build_alembic_config(db_url: str):
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _alembic_upgrade_head_sync(db_url: str) -> None:
    from alembic import command

    cfg = _build_alembic_config(db_url)
    command.upgrade(cfg, "head")


def _alembic_head_revision_sync(db_url: str) -> str | None:
    from alembic.script import ScriptDirectory

    cfg = _build_alembic_config(db_url)
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


_DB_URL = settings.DB_URL
_ensure_sqlite_dir(_DB_URL)

try:
    async_engine = create_async_engine(
        _DB_URL,
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


@asynccontextmanager
async def compat_session(scope_factory) -> AsyncIterator[Any]:
    """Adapt patched session_scope replacements used in tests."""

    cm = scope_factory()
    aenter = getattr(cm, "__aenter__", None)
    aexit = getattr(cm, "__aexit__", None)
    if callable(aenter) and callable(aexit):
        try:
            session = await aenter()
        except TypeError as exc:
            gen = getattr(cm, "gen", None)
            if gen is None or "async iterator" not in str(exc):
                raise
            try:
                session = next(gen)
            except StopIteration as stop:
                raise RuntimeError("session_scope stub yielded no session") from stop

            try:
                yield session
            finally:
                with suppress(StopIteration):
                    next(gen)
            return

        try:
            yield session
        finally:
            await aexit(None, None, None)
        return

    if hasattr(cm, "__enter__") and hasattr(cm, "__exit__"):
        with cm as session:
            yield session
        return

    if inspect.isawaitable(cm):
        session = await cm
        try:
            yield session
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        return

    raise TypeError("Unsupported session_scope replacement")


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


async def head_revision(db_url: str | None = None) -> str | None:
    url = db_url or settings.DB_URL
    try:
        return await asyncio.to_thread(_alembic_head_revision_sync, url)
    except Exception:
        log.exception("DB: get head revision failed")
        return None


async def upgrade_to_head(db_url: str | None = None, *, timeout: float | None = 15.0) -> bool:
    url = db_url or settings.DB_URL
    log.info("DB: alembic upgrade head — start")
    task = asyncio.to_thread(_alembic_upgrade_head_sync, url)
    try:
        if timeout is None:
            await task
        else:
            await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        log.error("DB: migration timeout, continue without blocking startup")
        return False
    except Exception:
        log.exception("DB: migration failed, continue without blocking startup")
        return False

    log.info("DB: alembic upgrade head — done")
    return True


async def init_db(engine: AsyncEngine | None = None) -> str | None:
    """Apply migrations with timeout and never block startup."""

    db_url = settings.DB_URL
    log.info("DB: url=%s migrate_on_start=%s", db_url, settings.MIGRATE_ON_START)

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

    if not settings.MIGRATE_ON_START:
        log.warning("DB: migrations skipped by flag")
        revision = await current_revision(db_url)
        log.info("DB: current revision=%s", revision or "unknown")
        return revision

    await upgrade_to_head(db_url=db_url, timeout=15.0)

    revision = await current_revision(db_url)
    log.info("DB: current revision=%s", revision or "unknown")
    return revision
