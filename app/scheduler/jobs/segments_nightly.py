from __future__ import annotations

import asyncio
import datetime as dt

from app.analytics.segments import build_features, cluster, persist

LOOKBACK_DAYS = 30


def _run_pipeline(start: dt.datetime, end: dt.datetime) -> int:
    features = build_features(start, end)
    mapping = cluster(features)
    persist(mapping)
    return len(mapping)


async def segments_nightly() -> None:
    """Rebuilds user segments from event logs."""

    end = dt.datetime.utcnow()
    start = end - dt.timedelta(days=LOOKBACK_DAYS)

    loop = asyncio.get_running_loop()
    try:
        updated = await loop.run_in_executor(None, _run_pipeline, start, end)
    except Exception as exc:
        print(f"[segments] failed to refresh segments: {exc}")
        return

    print(f"[segments] refreshed {updated} user segments")
