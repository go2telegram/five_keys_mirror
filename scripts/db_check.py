import asyncio
import importlib.util
import json
import os
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


def _emit_payload(
    *,
    tables: Iterable[str] | None,
    version: str | None,
    ok: bool,
    hint: str | None = None,
    error: str | None = None,
) -> int:
    payload: dict[str, object] = {
        "url": raw_url,
        "alembic_version": version,
        "tables": sorted(tables or []),
        "ok": ok,
    }
    if hint:
        payload["hint"] = hint
    if error:
        payload["error"] = error
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


def _default_hint(ok: bool) -> str | None:
    if ok:
        return None
    return "run alembic upgrade head"


def main() -> int:
    driver = drivername.split("+", 1)[1] if "+" in drivername else ""

    try:
        if driver == "aiosqlite" and _needs_driver("aiosqlite"):
            return _emit_payload(
                tables=[],
                version=None,
                ok=False,
                hint="install aiosqlite or run scripts/offline_install.ps1",
                error="missing driver: aiosqlite",
            )

        if driver == "asyncpg" and _needs_driver("asyncpg"):
            return _emit_payload(
                tables=[],
                version=None,
                ok=False,
                hint="install asyncpg or adjust DB_URL",
                error="missing driver: asyncpg",
            )

        if driver in {"aiosqlite", "asyncpg"}:
            tables, version = asyncio.run(_run_async(raw_url))
        else:
            tables, version = _run_sync(raw_url.replace("+aiosqlite", ""))

        ok = bool(version) and {"users", "events"} <= set(tables)
        return _emit_payload(tables=tables, version=version, ok=ok, hint=_default_hint(ok))
    except Exception as exc:  # pragma: no cover - defensive reporting
        return _emit_payload(
            tables=[],
            version=None,
            ok=False,
            hint="verify DB_URL and run alembic upgrade head",
            error=str(exc),
        )


if __name__ == "__main__":
    raise SystemExit(main())
