import importlib.util
import json
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv()
raw_url = os.getenv("DB_URL", "sqlite:///var/bot.db")

if raw_url.startswith("sqlite+") and "aiosqlite" in raw_url:
    if importlib.util.find_spec("aiosqlite") is None:
        print("missing driver: aiosqlite (install with pip install aiosqlite)")
        sys.exit(1)

url = raw_url.replace("+aiosqlite", "")
engine = create_engine(url, future=True)


def main() -> None:
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = inspector.get_table_names()
        version = None
        if "alembic_version" in tables:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        print(
            json.dumps(
                {
                    "url": url,
                    "alembic_version": version,
                    "tables": sorted(tables),
                    "ok": bool(version) and {"users", "events"} <= set(tables),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
