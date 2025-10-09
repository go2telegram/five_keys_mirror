#!/usr/bin/env python
"""Export events into CSV/Google Sheets/ClickHouse."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services import analytics


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_range(target: date) -> tuple[datetime, datetime]:
    since = datetime.combine(target, time.min, tzinfo=timezone.utc)
    until = since + timedelta(days=1)
    return since, until


async def _run(args: argparse.Namespace) -> int:
    if args.date:
        target_day = _parse_date(args.date)
    else:
        target_day = date.today() - timedelta(days=1)

    since, until = _build_range(target_day)

    csv_dir = Path(args.output_dir or settings.EVENTS_EXPORT_DIR)
    sheet_id = settings.GOOGLE_SHEET_ID if not args.no_google else None
    worksheet = settings.GOOGLE_EVENTS_WORKSHEET_TITLE
    clickhouse_url = None if args.no_clickhouse else (settings.CLICKHOUSE_URL or None)
    clickhouse_table = settings.CLICKHOUSE_TABLE if clickhouse_url else None

    result = await analytics.export_events_range(
        since,
        until,
        csv_dir=csv_dir,
        sheet_id=sheet_id,
        worksheet_title=worksheet if sheet_id else None,
        clickhouse_url=clickhouse_url,
        clickhouse_table=clickhouse_table,
    )

    print(f"[events-export] range={target_day.isoformat()} count={result.count}")
    if result.csv_path:
        print(f"  csv -> {result.csv_path}")
    if result.google_updated:
        print("  google sheets updated")
    if result.clickhouse_inserted:
        print("  clickhouse insert OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export analytics events")
    parser.add_argument("--date", help="target date in YYYY-MM-DD (defaults to yesterday)")
    parser.add_argument("--output-dir", help="directory for CSV export")
    parser.add_argument("--no-google", action="store_true", help="skip Google Sheets export")
    parser.add_argument("--no-clickhouse", action="store_true", help="skip ClickHouse export")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
