"""Event schema and parsing utilities for analytics ETL."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, Optional

__all__ = ["EventRecord", "parse_event_lines"]


def _parse_timestamp(raw: str) -> datetime:
    """Parse timestamps coming from the event log.

    ClickHouse and Parquet both work best with timezone-aware timestamps.  The
    application emits ISO-8601 timestamps, occasionally suffixed with ``Z`` or
    without an explicit timezone.  In the latter case we treat the value as UTC
    to guarantee consistent retention calculations.
    """

    if not raw:
        raise ValueError("Empty timestamp value")

    # ``datetime.fromisoformat`` cannot handle ``Z`` so we normalise to ``+00:00``.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@dataclass(slots=True)
class EventRecord:
    """A single analytics event ready to be loaded into storage."""

    ts: datetime
    user_id: str
    event: str
    props: Dict[str, Any]
    segment: Optional[str] = None
    source: Optional[str] = None

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "EventRecord":
        """Create an :class:`EventRecord` from a mapping.

        ``payload`` is expected to contain at least ``ts``, ``user_id`` and
        ``event`` keys.  ``props`` defaults to an empty mapping and other fields
        are optional.
        """

        try:
            ts_raw = payload["ts"]
            user_id = str(payload["user_id"])
            event = str(payload["event"])
        except KeyError as exc:  # pragma: no cover - defensive, critical error
            raise ValueError(f"Missing required field: {exc.args[0]}") from exc

        props = payload.get("props") or {}
        if not isinstance(props, dict):
            raise ValueError("props must be a JSON object")

        segment = payload.get("segment")
        source = payload.get("source")

        return cls(
            ts=_parse_timestamp(ts_raw),
            user_id=user_id,
            event=event,
            props=props,
            segment=str(segment) if segment is not None else None,
            source=str(source) if source is not None else None,
        )

    @classmethod
    def from_log_line(cls, line: str) -> "EventRecord":
        """Parse a log line with JSON payload into an :class:`EventRecord`."""

        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError("Log line must contain a JSON object")
        return cls.from_mapping(data)

    def to_row(self) -> Dict[str, Any]:
        """Convert the record into a serialisable dictionary."""

        return {
            "ts": self.ts,
            "user_id": self.user_id,
            "event": self.event,
            # Sorting keys keeps Parquet diffs deterministic and simplifies
            # ClickHouse JSONEachRow ingestion.
            "props": json.dumps(self.props, ensure_ascii=False, sort_keys=True),
            "segment": self.segment or "",
            "source": self.source or "",
        }


def parse_event_lines(lines: Iterable[str]) -> Iterator[EventRecord]:
    """Yield :class:`EventRecord` instances from raw log lines."""

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        yield EventRecord.from_log_line(raw)
