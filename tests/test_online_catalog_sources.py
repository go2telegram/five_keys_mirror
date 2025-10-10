import json
import os
import urllib.error

import pytest

from tools import build_products
from tools.build_products import enumerate_product_images, list_github_contents


@pytest.mark.network
def test_list_github_contents_products():
    os.environ["MEDIA_OWNER"] = "go2telegram"
    os.environ["MEDIA_REPO"] = "media"
    os.environ["MEDIA_REF"] = "main"
    try:
        items = list_github_contents("media/products", os.getenv("MEDIA_REF", "main"))
    except urllib.error.URLError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"Network unavailable: {exc}")
    assert isinstance(items, list)
    assert any(isinstance(entry, dict) and entry.get("type") == "file" for entry in items)


@pytest.mark.network
def test_enumerate_product_images_returns_urls():
    os.environ["MEDIA_REF"] = "main"
    try:
        urls = enumerate_product_images(os.getenv("MEDIA_REF", "main"))
    except urllib.error.URLError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"Network unavailable: {exc}")
    assert urls, "expected non-empty list of URLs"
    assert all(u.startswith("https://raw.githubusercontent.com/") for u in urls)


def test_build_catalog_respects_custom_remote_base(monkeypatch, tmp_path):
    custom_base = (
        "https://raw.githubusercontent.com/example/media/custom-ref/media/products"
    )

    monkeypatch.delenv("IMAGES_BASE", raising=False)
    monkeypatch.setenv("NO_NET", "0")

    monkeypatch.setattr(build_products, "_load_description_texts", lambda **_: [])
    monkeypatch.setattr(
        build_products,
        "_load_products",
        lambda _texts: [
            {
                "id": "foo",
                "title": "Foo",
                "order": {"velavie_link": "https://example.com"},
            }
        ],
    )
    monkeypatch.setattr(
        build_products,
        "_dedupe_products",
        lambda products, dedupe=True, strict=False: list(products),
    )

    captured: dict[str, tuple[str, str, str, str]] = {}

    def fake_enumerate_for(owner: str, repo: str, ref: str, path: str) -> list[str]:
        captured["params"] = (owner, repo, ref, path)
        return [
            f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}/foo.jpg"
        ]

    monkeypatch.setattr(
        build_products,
        "_enumerate_product_images_for",
        fake_enumerate_for,
    )

    def fail_enumerate_default(_ref: str) -> list[str]:  # pragma: no cover - ensures override used
        raise AssertionError("default enumerator should not be used")

    monkeypatch.setattr(build_products, "enumerate_product_images", fail_enumerate_default)

    def fail_list_remote(images_base: str) -> tuple[str, list[str]]:  # pragma: no cover
        raise AssertionError("fallback listing should not be used")

    monkeypatch.setattr(build_products, "_list_remote_images", fail_list_remote)

    output = tmp_path / "catalog.json"
    count, destination = build_products.build_catalog(
        descriptions_url=None,
        images_mode="remote",
        images_base=custom_base,
        output=output,
    )

    assert count == 1
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["products"][0]["image"].startswith(custom_base + "/")
    assert captured["params"] == ("example", "media", "custom-ref", "media/products")
