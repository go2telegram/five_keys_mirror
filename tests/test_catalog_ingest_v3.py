import json
import re
from urllib.parse import parse_qs, urlparse

CAT_PATH = "app/catalog/products.json"


def _load():
    with open(CAT_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["products"] if isinstance(data, dict) else data


def _find(products, pid):
    return next((item for item in products if item.get("id") == pid), None)


def test_catalog_has_expected_min_size():
    products = _load()
    assert len(products) >= 20, f"expected at least 20 products, got {len(products)}"


def test_slug_rules_examples():
    products = _load()
    assert _find(products, "nash-omega-3"), "slug for Omega-3 (30) not found"
    assert _find(products, "nash-omega-3-150"), "slug for Omega-3 (150) not found"
    assert _find(products, "t8-era-mit-up"), "slug for MIT UP not found"
    assert _find(products, "t8-stekla-black-96"), "slug for STЁKLA BLACK not found"


def test_images_mapping_examples():
    products = _load()
    product = _find(products, "nash-omega-3")
    assert product and (product.get("image") or product.get("images")), "Omega-3 image missing"
    image = product.get("image") or product.get("images", [None])[0]
    assert image and (image.endswith(".jpg") or image.endswith(".png") or image.endswith(".webp"))


def test_buy_url_has_utm():
    products = _load()
    product = _find(products, "t8-era-brain-coffee")
    assert product and product.get("order"), "Brain Coffee buy_url missing"
    url = product["order"]["velavie_link"]
    query = parse_qs(urlparse(url).query)
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        assert key in query, f"{key} not in buy_url"
    assert query["utm_source"] == ["tg_bot"]
    assert query["utm_medium"] == ["catalog"]
    assert query["utm_content"] == ["t8-era-brain-coffee"]
    assert re.match(r"^[a-z0-9\-]+$", query["utm_campaign"][0])
