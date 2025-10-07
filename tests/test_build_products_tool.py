import json
import logging
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tools.build_products import (
    _choose_image,
    build_catalog,
    main as build_main,
    quote_url,
    validate_catalog,
)


FIXTURE_DESCRIPTIONS = Path("tests/fixtures/catalog/descriptions/sample.txt")
FIXTURE_IMAGES_DIR = Path("tests/fixtures/catalog/images")


def _normalize_fixture_descriptions(destination: Path) -> Path:
    text = FIXTURE_DESCRIPTIONS.read_text(encoding="utf-8")
    blocks: list[list[str]] = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in {"====", "----"}:
            if buffer:
                blocks.append(buffer)
                buffer = []
            continue
        buffer.append(raw_line.rstrip())
    if buffer:
        blocks.append(buffer)

    normalized_blocks: list[str] = []
    for lines in blocks:
        fields: dict[str, str] = {}
        last_key: str | None = None
        extras: list[str] = []
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                normalized_key = key.strip().lower()
                fields[normalized_key] = value.strip()
                last_key = normalized_key
            elif line.strip():
                if last_key:
                    fields[last_key] = (fields.get(last_key, "") + " " + line.strip()).strip()
                else:
                    extras.append(line.strip())
        name = fields.get("название") or fields.get("name") or "Product"
        url = None
        for key in ("ссылка для заказа", "ссылка на покупку", "ссылка", "url"):
            if key in fields:
                url = fields[key]
                break
        if not url:
            continue
        body_parts: list[str] = []
        for key in ("кратко", "описание"):
            value = fields.get(key)
            if value:
                body_parts.append(value)
        if fields.get("применение"):
            body_parts.append(fields["применение"])
        body_parts.extend(extras)
        block_lines = [name]
        block_lines.extend(part for part in body_parts if part)
        block_lines.append(f"Ссылка для заказа: {url}")
        normalized_blocks.append("\n".join(block_lines))

    destination.write_text("\n\n".join(normalized_blocks), encoding="utf-8")
    return destination


def _prepare_fixture_catalog(tmp_path: Path) -> tuple[Path, Path]:
    descriptions_path = _normalize_fixture_descriptions(tmp_path / "descriptions.txt")
    images_dir = tmp_path / "images"
    shutil.copytree(FIXTURE_IMAGES_DIR, images_dir)
    return descriptions_path, images_dir


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
    assert quote_url(raw) == expected


def test_choose_image_heuristics_cover_common_variants() -> None:
    candidates = [
        "omega3_main.jpg",
        "mitup-main.webp",
        "stekla_01.png",
        "brain-coffee_main.jpg",
        "omega3_pack.webp",
    ]
    assert _choose_image("omega-3", candidates, used_images=set()) == "omega3_main.jpg"
    assert _choose_image("mit-up", candidates, used_images=set()) == "mitup-main.webp"
    assert _choose_image("stekla", candidates, used_images=set()) == "stekla_01.png"
    assert _choose_image("t8-era-brain-coffee", candidates, used_images=set()) == "brain-coffee_main.jpg"


def test_choose_image_respects_used_images() -> None:
    files = ["omega3_main.jpg", "omega3_main_copy.jpg"]
    used = {"omega3_main.jpg"}
    image = _choose_image("omega-3", files, used_images=used)
    assert image == "omega3_main_copy.jpg"


def test_build_catalog_with_fixture_assets(tmp_path: Path) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    output = tmp_path / "products.json"

    count, generated = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="add",
        strict_descriptions="add",
        output=output,
    )
    assert generated == output

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count == 11

    missing = [product for product in data["products"] if "missing_image" in product.get("tags", [])]
    assert missing and all(product["available"] is False for product in missing)
    for product in data["products"]:
        link = product["order"]["velavie_link"]
        if not link:
            continue
        params = parse_qs(urlparse(link).query)
        assert params["utm_source"] == ["tg_bot"]
        assert params["utm_medium"] == ["catalog"]
        assert params["utm_content"] == [product["id"]]

    validated = validate_catalog(output)
    assert validated == count


def test_build_catalog_creates_placeholder_for_unmatched_images(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    extra_image = images_dir / "mystery_main.png"
    extra_image.write_bytes(b"")

    output = tmp_path / "products.json"
    caplog.set_level(logging.WARNING)
    count, _ = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="add",
        strict_descriptions="add",
        output=output,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count == 12
    placeholders = [product for product in data["products"] if "unmatched_image" in product.get("tags", [])]
    assert len(placeholders) == 1
    placeholder = placeholders[0]
    assert placeholder["available"] is False
    assert placeholder["order"]["velavie_link"] == ""
    assert placeholder["images"] == [placeholder["image"]]
    assert placeholder["image"].endswith("mystery_main.png")
    assert any("Unmatched image" in record.message for record in caplog.records)


def test_strict_images_warn_skips_placeholder(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    (images_dir / "unused.webp").write_bytes(b"")

    output = tmp_path / "products.json"
    caplog.set_level(logging.WARNING)
    count, _ = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="warn",
        strict_descriptions="add",
        output=output,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count == 11
    assert not any("unmatched_image" in product.get("tags", []) for product in data["products"])
    assert any("Unmatched image (skipped)" in record.message for record in caplog.records)


def test_strict_images_off_ignores_unmatched(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    (images_dir / "ignored.png").write_bytes(b"")

    output = tmp_path / "products.json"
    caplog.set_level(logging.WARNING)
    count, _ = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="off",
        strict_descriptions="add",
        output=output,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == count == 11
    assert not any("unmatched_image" in product.get("tags", []) for product in data["products"])
    assert not any("Unmatched image" in record.message for record in caplog.records)


def test_strict_descriptions_warn_skips_missing_images(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)

    output = tmp_path / "products.json"
    caplog.set_level(logging.WARNING)
    count, _ = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="off",
        strict_descriptions="warn",
        output=output,
    )

    assert count == 10
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == 10
    assert not any("missing_image" in product.get("tags", []) for product in data["products"])
    assert any("Missing image" in record.message for record in caplog.records)


def test_strict_descriptions_off_skips_missing_images_without_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)

    output = tmp_path / "products.json"
    caplog.set_level(logging.WARNING)
    count, _ = build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="off",
        strict_descriptions="off",
        output=output,
    )

    assert count == 10
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["products"]) == 10
    assert not any("missing_image" in product.get("tags", []) for product in data["products"])
    assert any("Missing image" in record.message for record in caplog.records)


def test_cli_build_uses_argparse_and_outputs_file(tmp_path: Path) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    output = tmp_path / "cli-products.json"
    exit_code = build_main(
        [
            "build",
            "--descriptions-path",
            str(descriptions_path),
            "--images-dir",
            str(images_dir),
            "--images-mode",
            "local",
            "--strict-images",
            "add",
            "--strict-descriptions",
            "add",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["products"]


def test_cli_validate_returns_success(tmp_path: Path) -> None:
    descriptions_path, images_dir = _prepare_fixture_catalog(tmp_path)
    output = tmp_path / "products.json"
    build_catalog(
        descriptions_path=str(descriptions_path),
        images_mode="local",
        images_dir=str(images_dir),
        strict_images="add",
        strict_descriptions="add",
        output=output,
    )

    exit_code = build_main(["validate", "--source", str(output)])
    assert exit_code == 0
