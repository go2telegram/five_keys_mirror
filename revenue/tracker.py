"""Ingestion helpers for the revenue engine.

The tracker module provides two entrypoints:

* :func:`import_csv` — bulk import partner data exported from affiliate
  networks.
* :func:`handle_webhook` — a tiny adapter for webhook payloads.

Both helpers delegate persistence to :mod:`revenue.models` and return
structured information that can be reused by the bot or background jobs.
"""
from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import models


def _read_csv(path: Path | str) -> Iterable[dict[str, str]]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            yield {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()


def import_csv(path: Path | str) -> dict[str, Any]:
    """Import partner data from a CSV file.

    The CSV is expected to contain the following columns:

    * ``type`` — one of ``offer``/``click``/``conversion``/``payout``.
    * ``id`` — identifier of the record inside the partner system.
    * ``offer_id`` — (for clicks) the related offer identifier.
    * ``click_id`` — (for conversions) reference to the originating click.
    * ``conversion_id`` — (for payouts) reference to the conversion.
    * ``campaign`` — campaign name/identifier.
    * ``name`` — offer name.
    * ``cost`` — traffic cost (for clicks).
    * ``revenue`` — conversion revenue before payout adjustments.
    * ``amount`` — payout amount received.
    * ``timestamp`` — ISO 8601 string.

    Additional columns are ignored.
    """
    models.init_db()
    stats = {
        "offers": 0,
        "clicks": 0,
        "conversions": 0,
        "payouts": 0,
        "errors": [],
    }

    for row in _read_csv(path):
        record_type = (row.get("type") or "").lower()
        try:
            if record_type == "offer":
                external_id = row.get("id") or row.get("offer_id")
                if not external_id:
                    raise ValueError("offer_id is required")
                models.register_offer(
                    models.Offer(
                        external_id=external_id,
                        name=row.get("name") or "Unnamed offer",
                        campaign=row.get("campaign"),
                        default_payout=_to_float(row.get("default_payout")),
                    )
                )
                stats["offers"] += 1
            elif record_type == "click":
                external_id = row.get("id") or row.get("click_id")
                offer_id = row.get("offer_id") or row.get("offer")
                if not external_id:
                    raise ValueError("click_id is required")
                if not offer_id:
                    raise ValueError("offer_id is required for click")
                models.register_click(
                    models.Click(
                        external_id=external_id,
                        offer_id=offer_id,
                        campaign=row.get("campaign"),
                        occurred_at=_to_datetime(row.get("timestamp") or row.get("occurred_at")),
                        cost=_to_float(row.get("cost")),
                    )
                )
                stats["clicks"] += 1
            elif record_type == "conversion":
                external_id = row.get("id") or row.get("conversion_id")
                click_id = row.get("click_id") or row.get("click")
                if not external_id:
                    raise ValueError("conversion_id is required")
                if not click_id:
                    raise ValueError("click_id is required for conversion")
                models.register_conversion(
                    models.Conversion(
                        external_id=external_id,
                        click_id=click_id,
                        occurred_at=_to_datetime(row.get("timestamp") or row.get("occurred_at")),
                        revenue=_to_float(row.get("revenue")),
                        status=row.get("status") or "approved",
                    )
                )
                stats["conversions"] += 1
            elif record_type == "payout":
                external_id = row.get("id") or row.get("payout_id")
                conversion_id = row.get("conversion_id") or row.get("conversion")
                if not external_id:
                    raise ValueError("payout id is required")
                if not conversion_id:
                    raise ValueError("conversion_id is required for payout")
                models.register_payout(
                    models.Payout(
                        external_id=external_id,
                        conversion_id=conversion_id,
                        occurred_at=_to_datetime(row.get("timestamp") or row.get("occurred_at")),
                        amount=_to_float(row.get("amount") or row.get("revenue")),
                    )
                )
                stats["payouts"] += 1
            else:
                stats["errors"].append({"row": row, "error": "Unknown type"})
        except Exception as exc:  # pragma: no cover - defensive path
            stats["errors"].append({"row": row, "error": str(exc)})

    return stats


def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist webhook payloads coming from affiliate networks.

    The function is intentionally tolerant: it expects an ``event`` or ``type``
    key and a nested ``data`` object following the same schema as
    :func:`import_csv` rows.  The method returns the stored entity so that the
    caller can log or render it in admin interfaces.
    """
    models.init_db()
    event_type = (payload.get("event") or payload.get("type") or "").lower()
    data = payload.get("data") or payload

    if event_type == "offer":
        external_id = data.get("id") or data.get("offer_id")
        if not external_id:
            raise ValueError("offer_id is required")
        entity = models.Offer(
            external_id=external_id,
            name=data.get("name") or "Unnamed offer",
            campaign=data.get("campaign"),
            default_payout=_to_float(data.get("default_payout")),
        )
        models.register_offer(entity)
        return {"type": "offer", "data": asdict(entity)}

    if event_type == "click":
        external_id = data.get("id") or data.get("click_id")
        offer_id = data.get("offer_id") or data.get("offer")
        if not external_id:
            raise ValueError("click_id is required")
        if not offer_id:
            raise ValueError("offer_id is required for click")
        entity = models.Click(
            external_id=external_id,
            offer_id=offer_id,
            campaign=data.get("campaign"),
            occurred_at=_to_datetime(data.get("timestamp") or data.get("occurred_at")),
            cost=_to_float(data.get("cost")),
        )
        models.register_click(entity)
        return {"type": "click", "data": asdict(entity)}

    if event_type == "conversion":
        external_id = data.get("id") or data.get("conversion_id")
        click_id = data.get("click_id") or data.get("click")
        if not external_id:
            raise ValueError("conversion_id is required")
        if not click_id:
            raise ValueError("click_id is required for conversion")
        entity = models.Conversion(
            external_id=external_id,
            click_id=click_id,
            occurred_at=_to_datetime(data.get("timestamp") or data.get("occurred_at")),
            revenue=_to_float(data.get("revenue")),
            status=data.get("status") or "approved",
        )
        models.register_conversion(entity)
        return {"type": "conversion", "data": asdict(entity)}

    if event_type == "payout":
        external_id = data.get("id") or data.get("payout_id")
        conversion_id = data.get("conversion_id") or data.get("conversion")
        if not external_id:
            raise ValueError("payout id is required")
        if not conversion_id:
            raise ValueError("conversion_id is required for payout")
        entity = models.Payout(
            external_id=external_id,
            conversion_id=conversion_id,
            occurred_at=_to_datetime(data.get("timestamp") or data.get("occurred_at")),
            amount=_to_float(data.get("amount") or data.get("revenue")),
        )
        models.register_payout(entity)
        return {"type": "payout", "data": asdict(entity)}

    raise ValueError(f"Unsupported event type: {event_type}")


__all__ = ["import_csv", "handle_webhook"]
