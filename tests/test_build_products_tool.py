import json
from pathlib import Path
from textwrap import dedent
from urllib.parse import parse_qs, urlparse

import pytest

from tools import build_products as bp


DESCRIPTIONS_PATH = Path("app/catalog/descriptions/Полное описание продуктов vilavi.txt")
IMAGES_DIR = Path("app/static/images/products")
FIXTURE_IMAGES = Path("tests/fixtures/catalog/images")


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
    image = bp._choose_image("nash-omega-3", files)
    assert image == "omega3_main.jpg"
    image = bp._choose_image("t8-era-brain-coffee", files)
    assert image == "brain-coffee_main.jpg"


def test_build_catalog_with_local_assets(tmp_path: Path) -> None:
    output = tmp_path / "products.json"
    summary = bp.build_catalog(
        descriptions_path=str(DESCRIPTIONS_PATH),
        images_mode="local",
        images_dir=str(IMAGES_DIR),
        output=output,
    )
    assert summary.path == output
    assert summary.built >= 20

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == summary.built

    for product in data["products"]:
        link = product["order"]["velavie_link"]
        params = parse_qs(urlparse(link).query)
        assert params["utm_source"] == ["tg_bot"]
        assert params["utm_medium"] == ["catalog"]
        assert params["utm_content"] == [product["id"]]
        assert product.get("images")
        if product.get("image"):
            assert product["image"].startswith("/static/") or product["image"].startswith("http")

    validated = bp.validate_catalog(output)
    assert validated == summary.built


def test_build_cli_expect_count_fixed_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "products.json"
    description_file = tmp_path / "descriptions.txt"
    description_file.write_text(
        dedent(
            """
            T8 Blend
            Ссылка для заказа: https://shop.vilavi.com/Item/10001?ref=735861

            ====

            Slim Start
            Ссылка для заказа: https://shop.vilavi.com/Item/10002?ref=735861

            ====

            Missing Image Product
            Ссылка для заказа: https://shop.vilavi.com/Item/10003?ref=735861
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    exit_code = bp.main(
        [
            "build",
            "--descriptions-path",
            str(description_file),
            "--images-mode",
            "local",
            "--images-dir",
            str(FIXTURE_IMAGES),
            "--output",
            str(output),
            "--expect-count",
            "fixed:38",
            "--fail-on-mismatch",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "found_descriptions=" in captured.out
    assert "built=" in captured.out
    assert "missing_images=['missing-image-product']" in captured.out
