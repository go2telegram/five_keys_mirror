from __future__ import annotations

import datetime as dt

from app.storage import get_segment_summary

SEGMENT_ORDER = ["new", "returning", "payer", "dormant", "power"]


def render_metrics() -> str:
    summary, updated_at = get_segment_summary()
    lines = [
        "# HELP users_by_segment Number of users per lifecycle segment",
        "# TYPE users_by_segment gauge",
    ]

    for segment in SEGMENT_ORDER:
        value = summary.get(segment, 0)
        lines.append(f'users_by_segment{{segment="{segment}"}} {value}')

    for segment, value in summary.items():
        if segment not in SEGMENT_ORDER:
            lines.append(f'users_by_segment{{segment="{segment}"}} {value}')

    if updated_at:
        if isinstance(updated_at, dt.datetime):
            timestamp = updated_at.timestamp()
        else:
            timestamp = float(updated_at)
        lines.append("# HELP segments_last_updated Unix timestamp of last segment refresh")
        lines.append("# TYPE segments_last_updated gauge")
        lines.append(f"segments_last_updated {timestamp:.0f}")

    return "\n".join(lines) + "\n"
