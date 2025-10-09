#!/usr/bin/env python
"""Generate analytics reports for admins."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import session_scope
from app.services import analytics


async def _run(args: argparse.Namespace) -> int:
    since = until = None
    if args.days:
        until = datetime.now(timezone.utc)
        since = until - timedelta(days=args.days)

    async with session_scope() as session:
        if args.kind in ("funnel", "all"):
            stages = await analytics.funnel_stats(session, since=since, until=until)
            print(analytics.render_funnel_report(stages))
            print()
        if args.kind in ("cohort", "all"):
            rows = await analytics.cohort_retention(session, weeks=args.weeks)
            print(analytics.render_cohort_report(rows))
            print()
        if args.kind in ("ctr", "all"):
            ctr_rows = await analytics.ctr_stats(session, since=since, until=until, limit=args.limit)
            print(analytics.render_ctr_report(ctr_rows))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate analytics reports")
    parser.add_argument(
        "kind",
        choices=["funnel", "cohort", "ctr", "all"],
        default="all",
        nargs="?",
        help="Which report to generate",
    )
    parser.add_argument("--days", type=int, default=30, help="Time window for funnel/CTR reports")
    parser.add_argument("--weeks", type=int, default=8, help="Number of cohorts to include")
    parser.add_argument("--limit", type=int, default=10, help="Number of rows for CTR report")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
