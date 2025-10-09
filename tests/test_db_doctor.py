import pytest
from sqlalchemy import create_engine, text

from app.db import session


@pytest.mark.anyio("asyncio")
async def test_repair_stale_alembic_tables(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_engine(db_url.replace("+aiosqlite", ""), future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE _alembic_tmp_demo (id INTEGER)"))
            connection.execute(text("CREATE TABLE keep_me (id INTEGER)"))
    finally:
        engine.dispose()

    tables_before = await session.list_stale_alembic_tables(db_url)
    assert tables_before == ["_alembic_tmp_demo"]

    dropped = await session.repair_stale_alembic_tables(db_url)
    assert dropped == ["_alembic_tmp_demo"]

    tables_after = await session.list_stale_alembic_tables(db_url)
    assert tables_after == []
