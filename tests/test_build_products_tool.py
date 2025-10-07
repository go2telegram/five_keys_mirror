import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

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
        (
            "https://example.com/каталог/(продукт)/?utm_source=tg_bot",
            "https://example.com/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/%28%D0%BF%D1%80%D0%BE%D0%B4%D1%83%D0%BA%D1%82%29/?utm_source=tg_bot",
        ),
    ],
)
def test_quote_url_normalizes_path_and_query(raw: str, expected: str) -> None:
    assert bp.quote_url(raw) == expected


def test_merge_utm_adds_defaults_without_duplicates() -> None:
    url, utm = bp._merge_utm(
        "https://example.com/path/?ref=1&utm_source=existing&utm_medium=&utm_content=product",
        product_id="product",
        category="Drinks",
    )
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert params["utm_source"] == ["existing"]
    assert params["utm_medium"] == ["catalog"]
    assert params["utm_content"] == ["product"]
    assert params["utm_campaign"] == ["drinks"]
    assert parsed.path == "/path/"
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        assert parsed.query.count(f"{key}=") == 1
        assert utm[key] == params[key][0]


def test_choose_image_fallbacks() -> None:
    files = [
        "omega3_main.jpg",
        "brain-coffee_main.jpg",
        "misc/file.png",
        "omega3_pack.webp",
    ]
    image = bp._choose_image("nash-omega-3", files)
    assert image == "omega3_main.jpg"
    image = bp._choose_image("t8-era-brain-coffee", files)
    assert image == "brain-coffee_main.jpg"


def test_build_catalog_with_local_assets(tmp_path: Path) -> None:
    output = tmp_path / "products.json"
    count, generated = bp.build_catalog(
        descriptions_path=str(DESCRIPTIONS_PATH),
        images_mode="local",
        images_dir=str(IMAGES_DIR),
        output=output,
    )
    assert generated == output
    assert count >= 20

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count

    for product in data["products"]:
        link = product["order"]["velavie_link"]
        params = parse_qs(urlparse(link).query)
        assert params["utm_source"] == ["tg_bot"]
        assert params["utm_medium"] == ["catalog"]
        assert params["utm_content"] == [product["id"]]
        assert params["utm_campaign"]
        assert product.get("images")
        if product.get("image"):
            assert product["image"] == product["images"][0]
            assert product["image"].startswith("/static/") or product["image"].startswith("http")

    validated = bp.validate_catalog(output)
    assert validated == count
