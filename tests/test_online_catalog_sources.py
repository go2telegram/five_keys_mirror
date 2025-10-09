import os
import urllib.error

import pytest

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
