import csv
import json
from pathlib import Path

import pytest

from tools.build_mapping import run


def _write_json(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def temp_files(tmp_path: Path):
    images = tmp_path / "images.json"
    descriptions = tmp_path / "descriptions.json"
    csv_path = tmp_path / "catalog.csv"
    txt_path = tmp_path / "catalog.txt"
    return images, descriptions, csv_path, txt_path


def test_build_entries_all_ok(temp_files):
    images_path, descriptions_path, csv_path, txt_path = temp_files
    images = [
        {"file": f"image_{i:02d}.jpg", "variants": [f"product-{i:02d}"]}
        for i in range(38)
    ]
    descriptions = [
        {
            "id": f"product-{i:02d}",
            "title": f"Product {i:02d}",
            "short": "Short text",
            "description": "Long description",
            "usage": "Use it",
            "contra": "",
            "tags": ["tag"],
            "buy_url": "https://example.com/product",
            "category_slug": "supplements",
            "available": True,
        }
        for i in range(38)
    ]
    _write_json(images_path, images)
    _write_json(descriptions_path, descriptions)

    entries = run(
        images_path=images_path,
        descriptions_path=descriptions_path,
        csv_path=csv_path,
        txt_path=txt_path,
        expect_images=38,
    )

    assert len(entries) == 38
    assert all(entry.status == "ok" for entry in entries)

    with csv_path.open(encoding="utf-8") as handle:
        reader = list(csv.reader(handle))
    assert len(reader) == 39  # header + 38 rows

    text = txt_path.read_text(encoding="utf-8")
    blocks = [block for block in text.split("\n\n") if block.strip()]
    assert len(blocks) == 38


def test_utm_parameters_added(temp_files):
    images_path, descriptions_path, csv_path, txt_path = temp_files
    images = [{"file": "item.jpg", "variants": ["sample-item"]}]
    descriptions = [
        {
            "id": "sample-item",
            "title": "Sample Item",
            "short": "Short",
            "description": "Desc",
            "usage": "",
            "contra": "",
            "tags": [],
            "buy_url": "https://shop.example/item",
            "category_slug": "vitamins",
        }
    ]
    _write_json(images_path, images)
    _write_json(descriptions_path, descriptions)

    entries = run(
        images_path=images_path,
        descriptions_path=descriptions_path,
        csv_path=csv_path,
        txt_path=txt_path,
        expect_images=1,
    )

    assert entries[0].buy_url is not None
    assert "utm_source=tg_bot" in entries[0].buy_url
    assert "utm_medium=catalog" in entries[0].buy_url
    assert "utm_campaign=vitamins" in entries[0].buy_url
    assert "utm_content=sample-item" in entries[0].buy_url


def test_placeholder_and_missing_image(temp_files):
    images_path, descriptions_path, csv_path, txt_path = temp_files
    images = [{"file": "lonely.jpg", "variants": ["lonely-image"]}]
    descriptions = [
        {
            "id": "orphan-item",
            "title": "Orphan Item",
            "short": "",
            "description": "",
            "usage": "",
            "contra": "",
            "tags": [],
            "buy_url": "https://example.com/orphan",
            "category_slug": None,
        }
    ]
    _write_json(images_path, images)
    _write_json(descriptions_path, descriptions)

    entries = run(
        images_path=images_path,
        descriptions_path=descriptions_path,
        csv_path=csv_path,
        txt_path=txt_path,
    )

    assert len(entries) == 2
    placeholder = next(entry for entry in entries if entry.status == "placeholder")
    missing = next(entry for entry in entries if entry.status == "missing_image")

    assert placeholder.image_file == "lonely.jpg"
    assert placeholder.available is False
    assert "unmatched_image" in placeholder.tags
    assert placeholder.buy_url is None

    assert missing.product_id == "orphan-item"
    assert missing.available is False
    assert missing.buy_url and "utm_content=orphan-item" in missing.buy_url
