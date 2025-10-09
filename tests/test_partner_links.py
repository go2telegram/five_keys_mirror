import pytest

from app.handlers.commerce import _extract_partner_amount
from app.services.partner_links import PartnerLink, _validate_utms


@pytest.mark.parametrize(
    "final_url,expected",
    [
        ("https://example.com/p?utm_source=a&utm_medium=b", []),
        (
            "https://example.com/p?utm_source=a",
            ["utm utm_medium", "потерян после редиректа"],
        ),
    ],
)
def test_validate_utms_detects_missing(final_url, expected):
    link = PartnerLink(
        product_id="p1",
        title="Test",
        url="https://example.com/p?utm_source=a&utm_medium=b",
        utm={"utm_source": "a", "utm_medium": "b"},
    )
    issues = _validate_utms(link, final_url)
    for marker in expected:
        assert any(marker in issue for issue in issues)
    if not expected:
        assert issues == []


def test_validate_utms_requires_presence():
    link = PartnerLink(
        product_id="p2",
        title="NoUTM",
        url="https://example.com/p",
        utm={"utm_source": "src"},
    )
    issues = _validate_utms(link, "https://example.com/p")
    assert "utm utm_source отсутствует" in issues


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"amount": "123.45"}, 123.45),
        ({"revenue": "1 234,56"}, 1234.56),
        ({"value": "-50"}, 0.0),
        ({}, 0.0),
    ],
)
def test_extract_partner_amount(payload, expected):
    assert _extract_partner_amount(payload) == pytest.approx(expected)
