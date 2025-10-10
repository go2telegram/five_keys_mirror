"""Parsing and validation helpers for link manager imports."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from app.catalog.loader import load_catalog


@dataclass(slots=True)
class LinkRecord:
    """A single link entry parsed from import payload."""

    type: str
    id: str
    url: str


@dataclass(slots=True)
class ImportResult:
    """Validated payload summary with extracted link mapping."""

    total: int
    valid: int
    invalid_url: list[LinkRecord]
    unknown_ids: list[str]
    errors: list[str]
    register_url: str | None
    product_links: dict[str, str]
    expected_products: int

    @property
    def valid_products(self) -> int:
        return len(self.product_links)

    @property
    def can_apply(self) -> bool:
        return (
            self.valid > 0
            and not self.invalid_url
            and not self.unknown_ids
            and not self.errors
            and self.register_url is not None
            and self.valid_products == self.expected_products
        )


def _as_text(data: bytes | str) -> str:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="ignore")
    return data


def _parse_json(text: str) -> list[LinkRecord]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON import is not valid") from exc

    if isinstance(payload, dict):
        items = payload.get("links") or payload.get("items") or payload.get("data")
        if items is None:
            raise ValueError("JSON import must be an array or contain a 'links' array")
        payload = items

    if not isinstance(payload, list):
        raise ValueError("JSON import must contain an array of objects")

    records: list[LinkRecord] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        r_type = str(entry.get("type") or "").strip().lower()
        record_id = str(entry.get("id") or "").strip()
        url = str(entry.get("url") or "").strip()
        if r_type not in {"register", "product"}:
            continue
        if r_type == "product" and not record_id:
            continue
        records.append(LinkRecord(type=r_type, id=record_id, url=url))
    return records


def _parse_csv(text: str) -> list[LinkRecord]:
    buf = io.StringIO(text)
    reader = csv.DictReader(buf)
    records: list[LinkRecord] = []
    for row in reader:
        r_type = str(row.get("type") or "").strip().lower()
        record_id = str(row.get("id") or "").strip()
        url = str(row.get("url") or "").strip()
        if r_type not in {"register", "product"}:
            continue
        if r_type == "product" and not record_id:
            continue
        records.append(LinkRecord(type=r_type, id=record_id, url=url))
    return records


def parse_payload(data: bytes | str, *, filename: str | None = None) -> list[LinkRecord]:
    text = _as_text(data)
    guess = (filename or "").lower()
    if guess.endswith(".json"):
        return _parse_json(text)
    if guess.endswith(".csv"):
        return _parse_csv(text)
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return _parse_json(text)
    return _parse_csv(text)


def _is_valid_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    return True


def analyze_payload(records: Iterable[LinkRecord]) -> ImportResult:
    catalog = load_catalog()
    product_ids = set(catalog["products"].keys())

    valid_products: dict[str, str] = {}
    invalid_url: list[LinkRecord] = []
    unknown_ids: list[str] = []
    errors: list[str] = []
    register_url: str | None = None
    total = 0
    valid = 0

    for record in records:
        total += 1
        if record.type == "register":
            if _is_valid_url(record.url):
                register_url = record.url
                valid += 1
            else:
                invalid_url.append(record)
            continue

        if record.type != "product":
            errors.append(f"Unsupported type: {record.type}")
            continue

        if record.id not in product_ids:
            unknown_ids.append(record.id)
            continue

        if not _is_valid_url(record.url):
            invalid_url.append(record)
            continue

        valid_products[record.id] = record.url
        valid += 1

    return ImportResult(
        total=total,
        valid=valid,
        invalid_url=invalid_url,
        unknown_ids=unknown_ids,
        errors=errors,
        register_url=register_url,
        product_links=valid_products,
        expected_products=len(product_ids),
    )


__all__ = ["LinkRecord", "ImportResult", "parse_payload", "analyze_payload"]
