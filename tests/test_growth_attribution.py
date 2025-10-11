from __future__ import annotations

import pytest

from app.growth import attribution


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            "utm_source=TikTok&utm_medium=shorts&utm_campaign=Launch&utm_content=Video01",
            {
                "utm_source": "TikTok",
                "utm_medium": "shorts",
                "utm_campaign": "Launch",
                "utm_content": "Video01",
            },
        ),
        (
            "utm_source=tiktok&utm_medium=Shorts&utm_campaign=%20launch%20",
            {
                "utm_source": "tiktok",
                "utm_medium": "Shorts",
                "utm_campaign": "launch",
            },
        ),
    ],
)
def test_parse_utm_payload(payload: str, expected: dict[str, str]) -> None:
    parsed = attribution.parse_utm_payload(payload)
    assert parsed == expected


def test_parse_utm_payload_ignores_unknown_keys() -> None:
    payload = "utm_source=test&utm_medium=ads&utm_term=value"
    parsed = attribution.parse_utm_payload(payload)
    assert parsed == {"utm_source": "test", "utm_medium": "ads"}


def test_build_start_payload_encodes_query() -> None:
    raw, encoded = attribution.build_start_payload(
        {
            "utm_source": "you tube",
            "utm_medium": "shorts",
            "utm_campaign": "winter",
            "utm_content": "clip-01",
        }
    )
    assert raw == "utm_source=you+tube&utm_medium=shorts&utm_campaign=winter&utm_content=clip-01"
    assert encoded == ("utm_source%3Dyou%2Btube%26utm_medium%3Dshorts%26utm_campaign%3Dwinter%26utm_content%3Dclip-01")


@pytest.mark.parametrize(
    "key, label",
    [
        (("tiktok", "shorts", "winter", "clip"), "tiktok · shorts · winter · clip"),
        (("—", "—", "—", "—"), "unknown"),
    ],
)
def test_format_utm_label(key: attribution.UtmKey, label: str) -> None:
    assert attribution.format_utm_label(key) == label
