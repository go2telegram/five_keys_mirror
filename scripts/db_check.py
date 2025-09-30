import json
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv()
url = os.getenv("DB_URL", "sqlite:///var/bot.db").replace("+aiosqlite", "")
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
