import asyncio
import importlib.util
import json
import os
import sys
from typing import Iterable, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

load_dotenv()
raw_url = os.getenv("DB_URL", "sqlite:///var/bot.db")
url_obj = make_url(raw_url)
drivername = url_obj.drivername


def _needs_driver(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is None


def _collect_metadata(connection) -> Tuple[Iterable[str], str | None]:
    inspector = inspect(connection)
    tables = inspector.get_table_names()
    version = None
    if "alembic_version" in tables:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    return tables, version


def _format_and_print(tables: Iterable[str], version: str | None) -> int:
    tables_list = sorted(tables)
    ok = bool(version) and {"users", "events"} <= set(tables_list)
    payload = {
        "url": raw_url,
        "alembic_version": version,
        "tables": tables_list,
        "ok": ok,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def _run_sync(url: str) -> Tuple[Iterable[str], str | None]:
    engine = create_engine(url, future=True)
    with engine.connect() as connection:
        return _collect_metadata(connection)


async def _run_async(url: str) -> Tuple[Iterable[str], str | None]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, future=True)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_collect_metadata)
    finally:
        await engine.dispose()


def main() -> int:
    driver = drivername.split("+", 1)[1] if "+" in drivername else ""
    if driver == "aiosqlite" and _needs_driver("aiosqlite"):
        print("missing driver: aiosqlite (install with pip install aiosqlite)")
        return 1

    if driver == "asyncpg" and _needs_driver("asyncpg"):
        print("missing driver: asyncpg (install with pip install asyncpg)")
        return 1

    if driver in {"aiosqlite", "asyncpg"}:
        tables, version = asyncio.run(_run_async(raw_url))
    else:
        tables, version = _run_sync(raw_url.replace("+aiosqlite", ""))

    return _format_and_print(tables, version)


if __name__ == "__main__":
    raise SystemExit(main())
