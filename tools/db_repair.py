"""Repair Alembic leftovers and re-apply migrations."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.session import current_revision, head_revision, upgrade_to_head

_TEMP_PREFIX = "_alembic_tmp_"
log = logging.getLogger("db_repair")


def _quote(identifier: str) -> str:
    return identifier.replace("\"", "\"\"")


async def _cleanup_temp_objects(db_url: str) -> None:
    engine = create_async_engine(db_url, future=True)

    def _drop_temp_objects_sync(connection) -> None:
        inspector = inspect(connection)
        temp_tables = [name for name in inspector.get_table_names() if name.startswith(_TEMP_PREFIX)]
        for name in temp_tables:
            log.info("Dropping temporary table %s", name)
            connection.execute(text(f'DROP TABLE IF EXISTS "{_quote(name)}"'))

        dropped_indexes: set[str] = set()
        for table_name in inspector.get_table_names():
            for index in inspector.get_indexes(table_name):
                idx_name = index.get("name")
                if isinstance(idx_name, str) and idx_name.startswith(_TEMP_PREFIX) and idx_name not in dropped_indexes:
                    log.info("Dropping temporary index %s", idx_name)
                    connection.execute(text(f'DROP INDEX IF EXISTS "{_quote(idx_name)}"'))
                    dropped_indexes.add(idx_name)

    try:
        async with engine.begin() as connection:
            dialect = connection.dialect.name
            log.info("Connected to %s database", dialect)

            if dialect == "sqlite":
                table_stmt = text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE :prefix"
                )
                index_stmt = text(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE :prefix"
                )
                tables = (await connection.execute(table_stmt, {"prefix": f"{_TEMP_PREFIX}%"})).scalars().all()
                indexes = (await connection.execute(index_stmt, {"prefix": f"{_TEMP_PREFIX}%"})).scalars().all()
                for name in tables:
                    log.info("Dropping temporary table %s", name)
                    await connection.execute(text(f'DROP TABLE IF EXISTS "{_quote(name)}"'))
                for name in indexes:
                    log.info("Dropping temporary index %s", name)
                    await connection.execute(text(f'DROP INDEX IF EXISTS "{_quote(name)}"'))
            else:
                await connection.run_sync(_drop_temp_objects_sync)

        log.info("Temporary Alembic artefacts removed")
    finally:
        await engine.dispose()


async def _repair(db_url: str) -> int:
    log.info("Starting database repair for %s", db_url)
    await _cleanup_temp_objects(db_url)

    log.info("Running alembic upgrade head")
    applied = await upgrade_to_head(db_url=db_url, timeout=None)
    current = await current_revision(db_url)
    head = await head_revision(db_url)
    log.info("Current revision: %s (head: %s)", current or "unknown", head or "unknown")
    return 0 if applied else 1


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    exit_code = await _repair(settings.DB_URL)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
