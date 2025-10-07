import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tools import build_products as bp


DESCRIPTIONS_PATH = Path("app/catalog/descriptions/Полное описание продуктов vilavi.txt")
IMAGES_DIR = Path("app/static/images/products")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "https://example.com/путь/страница 1?ключ=значение&param=a b",
            "https://example.com/%D0%BF%D1%83%D1%82%D1%8C/%D1%81%D1%82%D1%80%D0%B0%D0%BD%D0%B8%D1%86%D0%B0%201?%D0%BA%D0%BB%D1%8E%D1%87=%D0%B7%D0%BD%D0%B0%D1%87%D0%B5%D0%BD%D0%B8%D0%B5&param=a+b",
        ),
        (
            "https://example.com/a path/?q=знач",
            "https://example.com/a%20path/?q=%D0%B7%D0%BD%D0%B0%D1%87",
        ),
    ],
)
def test_quote_url_normalizes_path_and_query(raw: str, expected: str) -> None:
    assert bp.quote_url(raw) == expected


def test_choose_image_fallbacks() -> None:
    files = [
        "omega3_main.jpg",
        "brain-coffee_main.jpg",
        "misc/file.png",
        "omega3_pack.webp",
    ]
    image = bp._choose_image("nash-omega-3", files, used_images=set())
    assert image == "omega3_main.jpg"
    image = bp._choose_image("t8-era-brain-coffee", files, used_images=set())
    assert image == "brain-coffee_main.jpg"


def test_choose_image_respects_used_images() -> None:
    files = ["omega3_main.jpg", "omega3_main_copy.jpg"]
    used = {"omega3_main.jpg"}
    image = bp._choose_image("omega-3", files, used_images=used)
    assert image == "omega3_main_copy.jpg"


def test_build_catalog_with_local_assets(tmp_path: Path) -> None:
    output = tmp_path / "products.json"
    count, generated = bp.build_catalog(
        descriptions_path=str(DESCRIPTIONS_PATH),
        images_mode="local",
        images_dir=str(IMAGES_DIR),
        strict_images="add",
        strict_descriptions="add",
        output=output,
    )
    assert generated == output
    assert count >= 20

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count

    for product in data["products"]:
        link = product["order"]["velavie_link"]
        if not link:
            continue
        params = parse_qs(urlparse(link).query)
        assert params["utm_source"] == ["tg_bot"]
        assert params["utm_medium"] == ["catalog"]
        assert params["utm_content"] == [product["id"]]
        if "missing_image" in product.get("tags", []):
            assert product.get("images") == []
            continue
        assert product.get("images")
        if product.get("image"):
            assert product["image"].startswith("/static/") or product["image"].startswith("http")

    if all(product["order"]["velavie_link"] for product in data["products"]):
        validated = bp.validate_catalog(output)
        assert validated == count


def test_build_catalog_creates_minimal_cards(tmp_path: Path) -> None:
    descriptions = tmp_path / "descriptions.txt"
    descriptions.write_text(
        """
Omega 3

Описание продукта

Ссылка для заказа: https://example.com/omega
""".strip(),
        encoding="utf-8",
    )
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "omega-3.jpg").write_text("", encoding="utf-8")
    (images_dir / "extra_main.png").write_text("", encoding="utf-8")

    output = tmp_path / "products.json"
    count, _ = bp.build_catalog(
        descriptions_path=str(descriptions),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="add",
        strict_descriptions="add",
        output=output,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert count == len(data["products"]) == 2
    omega = next(item for item in data["products"] if item["title"] == "Omega 3")
    assert omega["image"].endswith("omega-3.jpg")
    assert omega["id"].startswith("omega")

    unmatched = next(item for item in data["products"] if "unmatched_image" in item["tags"])
    assert unmatched["available"] is False
    assert unmatched["order"]["velavie_link"] == ""
    assert unmatched["image"].endswith("extra_main.png")
    assert unmatched["title"] == "Extra"
    assert unmatched["images"] == [unmatched["image"]]


def test_build_catalog_marks_missing_image(tmp_path: Path) -> None:
    descriptions = tmp_path / "single.txt"
    descriptions.write_text(
        """
No Image Product

Описание

Ссылка для заказа: https://example.com/no-image
""".strip(),
        encoding="utf-8",
    )
    images_dir = tmp_path / "images"
    images_dir.mkdir()

    output = tmp_path / "products.json"
    count, _ = bp.build_catalog(
        descriptions_path=str(descriptions),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="off",
        strict_descriptions="add",
        output=output,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert count == len(data["products"]) == 1
    product = data["products"][0]
    assert product["available"] is False
    assert "missing_image" in product["tags"]
    assert product.get("images") == []
