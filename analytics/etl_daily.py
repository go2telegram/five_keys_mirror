"""Daily ETL script for exporting analytics events."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

import pandas as pd

from analytics.schema import EventRecord, parse_event_lines
from config import CLICKHOUSE_URL, DATA_DIR, LOGS_DIR

try:  # pragma: no cover - optional dependency
    import httpx
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit("httpx must be installed to run the ETL") from exc

LOG_PATH = LOGS_DIR / "events.log"
DEFAULT_TABLE = "analytics.events"


def _date_range(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _filter_by_date(records: Iterable[EventRecord], start: datetime, end: datetime) -> List[EventRecord]:
    return [record for record in records if start <= record.ts < end]


def _prepare_dataframe(records: Sequence[EventRecord]) -> pd.DataFrame:
    rows = [record.to_row() for record in records]
    if not rows:
        # Create an empty dataframe with the schema so parquet files keep
        # consistent metadata.
        rows = [
            {
                "ts": pd.Timestamp("1970-01-01T00:00:00Z"),
                "user_id": "",
                "event": "",
                "props": json.dumps({}, ensure_ascii=False, sort_keys=True),
                "segment": "",
                "source": "",
            }
        ]
        df = pd.DataFrame(rows).iloc[:0]
    else:
        df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _ensure_clickhouse_database(client: httpx.Client, table: str = DEFAULT_TABLE) -> None:
    database, _, table_name = table.partition(".")
    if not table_name:
        raise ValueError("CLICKHOUSE table must include database name, e.g. analytics.events")

    client.post("/", content=f"CREATE DATABASE IF NOT EXISTS {database}")
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {table} (
        ts DateTime64(3, 'UTC'),
        user_id String,
        event String,
        props JSON,
        segment String,
        source String
    )
    ENGINE = MergeTree
    ORDER BY (ts, user_id)
    SETTINGS index_granularity = 8192
    """
    client.post("/", content=ddl)


def _load_into_clickhouse(records: Sequence[EventRecord], table: str = DEFAULT_TABLE) -> None:
    if not records:
        return

    with httpx.Client(base_url=CLICKHOUSE_URL, timeout=30.0) as client:
        _ensure_clickhouse_database(client, table=table)
        payload = "\n".join(
            json.dumps(record.to_row(), ensure_ascii=False, sort_keys=True) for record in records
        )
        response = client.post(
            "/",
            params={"query": f"INSERT INTO {table} FORMAT JSONEachRow"},
            content=payload.encode("utf-8"),
        )
        response.raise_for_status()



def _load_into_parquet(records: Sequence[EventRecord], target_date: date) -> Path:
    df = _prepare_dataframe(records)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / f"events_{target_date.strftime('%Y%m%d')}.parquet"
    df.to_parquet(output_path, engine="pyarrow", index=False)
    return output_path


def run_etl(target_date: date, sink: str, table: str = DEFAULT_TABLE) -> Path | None:
    if LOG_PATH.exists():
        with LOG_PATH.open("r", encoding="utf-8") as handle:
            parsed_records = list(parse_event_lines(handle))
    else:
        logging.warning("Event log %s does not exist; producing empty dataset", LOG_PATH)
        parsed_records = []

    start, end = _date_range(target_date)

    filtered_records = _filter_by_date(parsed_records, start, end)
    logging.info("Read %d events, %d for target date", len(parsed_records), len(filtered_records))

    if sink == "parquet":
        return _load_into_parquet(filtered_records, target_date)
    if sink == "clickhouse":
        _load_into_clickhouse(filtered_records, table=table)
        return None
    raise ValueError("sink must be either 'parquet' or 'clickhouse'")



def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily analytics ETL")
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD format")
    parser.add_argument("--sink", choices=["parquet", "clickhouse"], default="parquet")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help="ClickHouse table name including database (default: analytics.events)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO)",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")

    try:
        target_date = datetime.fromisoformat(args.date).date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date '{args.date}': {exc}") from exc

    result = run_etl(target_date=target_date, sink=args.sink, table=args.table)
    if result:
        logging.info("Wrote %s", result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
