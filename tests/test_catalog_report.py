from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.catalog.report import (
    CatalogReport,
    CatalogReportError,
    get_catalog_report,
)


def test_get_catalog_report_prefers_report_file(tmp_path: Path) -> None:
    catalog_path = tmp_path / "products.json"
    catalog_path.write_text(json.dumps({"products": []}), encoding="utf-8")

    report_path = tmp_path / "products.report.json"
    report_payload = {
        "built": 7,
        "found_images": 10,
        "found_descriptions": 8,
        "missing_images": ["a.jpg", "b.jpg"],
        "unmatched_images": ["c.jpg"],
        "catalog_path": str(catalog_path),
        "generated_at": "2024-01-01T00:00:00+00:00",
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    report = get_catalog_report(report_path=report_path, catalog_path=catalog_path)

    assert isinstance(report, CatalogReport)
    assert report.built == 7
    assert report.found_images == 10
    assert report.found_descriptions == 8
    assert report.missing_images == ["a.jpg", "b.jpg"]
    assert report.unmatched_images == ["c.jpg"]
    assert report.catalog_path == catalog_path
    assert report.generated_at == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_get_catalog_report_fallback_to_catalog_json(tmp_path: Path) -> None:
    catalog_path = tmp_path / "products.json"
    products = [
        {
            "id": "alpha",
            "title": "Alpha",
            "order": {"velavie_link": "https://example.com/a"},
            "images": [
                "/static/images/products/alpha.jpg",
                "https://cdn.example.com/alpha_remote.jpg",
            ],
        },
        {
            "id": "beta",
            "title": "Beta",
            "order": {"velavie_link": "https://example.com/b"},
            "images": ["/static/images/products/beta.jpg"],
        },
    ]
    catalog_path.write_text(json.dumps({"products": products}), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "alpha.jpg").write_bytes(b"alpha")
    (images_dir / "extra.jpg").write_bytes(b"extra")

    timestamp = 1_700_000_000
    os_stat_time = (timestamp, timestamp)
    os.utime(catalog_path, os_stat_time)

    report = get_catalog_report(
        report_path=tmp_path / "missing.report.json",
        catalog_path=catalog_path,
        images_dir=images_dir,
    )

    assert report.built == 2
    assert report.found_descriptions == 2
    assert report.found_images == 2  # alpha.jpg + extra.jpg
    assert report.missing_images == ["beta.jpg"]
    assert report.unmatched_images == ["extra.jpg"]
    assert report.catalog_path == catalog_path
    assert report.generated_at == datetime.fromtimestamp(timestamp, tz=timezone.utc)


def test_get_catalog_report_raises_on_missing_catalog(tmp_path: Path) -> None:
    with pytest.raises(CatalogReportError):
        get_catalog_report(
            report_path=tmp_path / "missing.report.json",
            catalog_path=tmp_path / "missing.json",
            images_dir=tmp_path / "images",
        )
