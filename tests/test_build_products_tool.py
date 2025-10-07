from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest

from tools import build_products as bp


def test_slugify_variants():
    assert bp._slugify("Omega 3") == "omega-3"
    variants = bp._slug_variants("Omega-3")
    assert "omega3" in variants
    assert "omega_3" in variants


@pytest.fixture(scope="module")
def fixture_paths() -> dict[str, Path]:
    base = Path(__file__).parent / "fixtures" / "catalog"
    return {
        "descriptions": base / "descriptions",
        "images": base / "images",
    }


def test_build_and_validate_catalog(tmp_path: Path, fixture_paths: dict[str, Path]):
    output = tmp_path / "products.json"
    count, path = bp.build_catalog(
        descriptions_url=str(fixture_paths["descriptions"]),
        images_base=str(fixture_paths["images"]),
        output=output,
    )

    assert path == output
    assert count > 9

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count

    missing_images = 0
    for product in data["products"]:
        link = product["order"]["velavie_link"]
        parsed = urlparse(link)
        params = dict(parse_qsl(parsed.query))
        assert params["utm_source"] == "tg_bot"
        assert params["utm_medium"] == "catalog"
        assert params["utm_campaign"]
        assert params["utm_content"]
        if not product.get("available", True):
            missing_images += 1
        else:
            assert product.get("images"), product["id"]

    assert missing_images == 1

    validated = bp.validate_catalog(output)
    assert validated == count


def test_image_mapping_synonyms(fixture_paths: dict[str, Path]):
    base, files = bp._load_image_index(str(fixture_paths["images"]))
    lookup = bp._build_image_lookup(files)
    assert base.endswith("fixtures/catalog/images")

    slug = bp._slugify("omega-3")
    image = bp._select_image(slug, lookup)
    assert image and image.endswith("omega3_main.jpg")

    slug = bp._slugify("Immuno Guard")
    image = bp._select_image(slug, lookup)
    assert image and image.endswith("immuno_guard-main.jpeg")

    slug = bp._slugify("Slim Start")
    image = bp._select_image(slug, lookup)
    assert image and image.endswith("slimstart.png")
