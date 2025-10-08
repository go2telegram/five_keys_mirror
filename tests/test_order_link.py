from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.reco import OrderLinkError, build_order_link


def test_build_order_link_overrides_utm_params() -> None:
    url = build_order_link("t8-beet-shot", "energy-focus")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["utm_source"] == ["tg_bot"]
    assert query["utm_medium"] == ["recommend"]
    assert query["utm_campaign"] == ["energy-focus"]
    assert query["utm_content"] == ["t8-beet-shot"]
    assert "ref" in query


def test_build_order_link_preserves_unicode_campaign() -> None:
    url = build_order_link("sertifikat-o-test", "подарок весна")
    query = parse_qs(urlparse(url).query)
    assert query["utm_campaign"] == ["подарок весна"]
    assert query["utm_content"] == ["sertifikat-o-test"]


def test_build_order_link_errors_on_unknown_product() -> None:
    with pytest.raises(OrderLinkError):
        build_order_link("missing", "energy")
