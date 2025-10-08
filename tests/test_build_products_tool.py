import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

import pytest

from tools import build_products as bp


DESCRIPTIONS_DIR = Path("tests/fixtures/catalog/descriptions_multi")


DESCRIPTIONS_PATH = Path("app/catalog/descriptions/Полное описание продуктов vilavi.txt")
IMAGES_DIR = Path("app/static/images/products")


def test_normalize_images_directory_flattens_nested_structure(tmp_path: Path) -> None:
    base = tmp_path / "products"
    nested = base / "images"
    deeper = nested / "more"
    deeper.mkdir(parents=True)
    (nested / "alpha.jpg").write_bytes(b"alpha")
    (deeper / "beta.png").write_bytes(b"beta")

    listed = bp._list_local_images(base)
    assert sorted(listed) == ["alpha.jpg", "more/beta.png"]
    assert nested.exists()

    changed = bp.normalize_images_directory(base)
    assert changed is True
    assert not nested.exists()

    files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
    assert files == ["alpha.jpg", "more/beta.png"]


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


@pytest.mark.parametrize(
    "slug_value, candidate",
    [
        ("nash-omega-3", "omega3_main.jpg"),
        ("t8-era-mit-up", "mitup_main.png"),
        ("t8-stekla-black-96", "stёkla-main.jpg"),
    ],
)
def test_match_image_alias_variants(slug_value: str, candidate: str) -> None:
    match = bp._match_image(slug_value, [candidate])
    assert match is not None
    assert match.name == candidate
    assert match.alias is not None


def test_slug_transliterates_yo() -> None:
    assert bp._slug("СТЁКЛА Black 96") == "stekla-black-96"


def test_build_catalog_with_local_assets(tmp_path: Path) -> None:
    output = tmp_path / "products.json"
    summary_path = tmp_path / "report.json"
    count, generated = bp.build_catalog(
        descriptions_path=str(DESCRIPTIONS_PATH),
        images_mode="local",
        images_dir=str(IMAGES_DIR),
        output=output,
        summary_path=summary_path,
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

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["built"] == count
    assert summary["catalog_path"] == str(output)


def test_load_description_texts_combines_multiple_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    remote_api = "https://api.github.com/repos/example/repo/contents/descriptions?ref=main"
    remote_files = {
        "https://raw.githubusercontent.com/example/repo/main/descriptions/remote1.txt": "Продукт Эхо\nСсылка для заказа: https://shop.example.com/e",
        "https://raw.githubusercontent.com/example/repo/main/descriptions/remote2.txt": "Продукт Фокстрот\nСсылка для заказа: https://shop.example.com/f",
    }

    def fake_http_get(url: str, *, accept: str | None = None) -> bytes:
        if url == remote_api:
            payload = [
                {
                    "type": "file",
                    "path": "descriptions/remote1.txt",
                    "download_url": "https://raw.githubusercontent.com/example/repo/main/descriptions/remote1.txt",
                },
                {
                    "type": "file",
                    "path": "descriptions/remote2.txt",
                    "download_url": "https://raw.githubusercontent.com/example/repo/main/descriptions/remote2.txt",
                },
            ]
            return json.dumps(payload).encode("utf-8")
        if url in remote_files:
            return remote_files[url].encode("utf-8")
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(bp, "_http_get", fake_http_get)

    texts = bp._load_description_texts(
        descriptions_path=str(DESCRIPTIONS_DIR),
        descriptions_url="https://github.com/example/repo/tree/main/descriptions",
    )

    origins = [origin for origin, _ in texts]
    assert len(texts) == 5
    assert any(origin.endswith("first.txt") for origin in origins)
    assert any(origin.endswith("second.txt") for origin in origins)
    assert any(origin.endswith("third.txt") for origin in origins)
    assert remote_files.keys() <= set(origins)


def test_dedupe_products_removes_duplicates() -> None:
    base_products = [
        {"title": " Product Alpha ", "name": " Product Alpha ", "order": {"velavie_link": " https://shop.example.com/a "}},
        {"title": "Product Alpha", "name": "Product Alpha", "order": {"velavie_link": "https://shop.example.com/a"}},
        {"title": "Product Bravo", "name": "Product Bravo", "order": {"velavie_link": "https://shop.example.com/b"}},
    ]

    deduped = bp._dedupe_products([product.copy() for product in base_products], dedupe=True)
    assert [item["title"] for item in deduped] == ["Product Alpha", "Product Bravo"]

    without_dedupe = bp._dedupe_products([product.copy() for product in base_products], dedupe=False)
    assert [item["title"] for item in without_dedupe] == ["Product Alpha", "Product Alpha", "Product Bravo"]


def test_build_catalog_writes_summary(tmp_path: Path) -> None:
    output = tmp_path / "products.json"
    summary_path = tmp_path / "summary.json"
    count, _ = bp.build_catalog(
        descriptions_path=str(DESCRIPTIONS_PATH),
        images_mode="local",
        images_dir=str(IMAGES_DIR),
        output=output,
        summary_path=summary_path,
    )

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["built"] == count
    assert payload["catalog_path"] == str(output)
    assert payload["found_images"] == len(bp._list_local_images(Path(IMAGES_DIR)))
    assert "generated_at" in payload


def test_expect_count_from_images_mismatch(tmp_path: Path) -> None:
    descriptions_path = str(DESCRIPTIONS_PATH)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "placeholder.jpg").write_bytes(b"x")
    output = tmp_path / "products.json"
    summary_path = tmp_path / "summary.json"

    with pytest.raises(bp.CatalogBuildError) as exc:
        bp.build_catalog(
            descriptions_path=descriptions_path,
            images_mode="local",
            images_dir=str(images_dir),
            output=output,
            summary_path=summary_path,
            expect_count="from=images",
            fail_on_mismatch=True,
        )

    message = str(exc.value)
    assert "expected 1" in message

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["found_images"] == 1
    assert payload["built"] != payload["found_images"]
    assert payload["unmatched_images"] == ["placeholder.jpg"]
