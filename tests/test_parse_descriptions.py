from __future__ import annotations

from pathlib import Path

import pytest

from tools.parse_descriptions import build_index


DESCRIPTIONS_FILE = Path("app/catalog/descriptions/Полное описание продуктов vilavi.txt")


@pytest.fixture(scope="module")
def descriptions_index() -> list[dict[str, object]]:
    return build_index(DESCRIPTIONS_FILE)


def _get_record(index: list[dict[str, object]], product_id: str) -> dict[str, object]:
    for item in index:
        if item.get("id") == product_id:
            return item
    raise AssertionError(f"Product {product_id} not found")


def test_index_contains_expected_volume(descriptions_index: list[dict[str, object]]) -> None:
    assert len(descriptions_index) >= 25


def test_omega3_capsules_parsed(descriptions_index: list[dict[str, object]]) -> None:
    product = _get_record(descriptions_index, "nash-omega-3")
    assert product["buy_url"] == "https://vlv-shop.ru/ru-ru/app/catalog/28/49596?ref=735861"
    assert "omega" in product["tags"]
    assert "contra" in product and "непереносимость" in product["contra"].lower()


def test_mit_up_has_usage_and_aliases(descriptions_index: list[dict[str, object]]) -> None:
    product = _get_record(descriptions_index, "t8-era-mit-up")
    assert product["buy_url"].endswith("/14/39176?ref=735861")
    assert product["usage"].startswith("По 1 стику в день")
    assert "mit" in product["aliases"]


def test_blend_contains_composition(descriptions_index: list[dict[str, object]]) -> None:
    product = _get_record(descriptions_index, "t8-blend-90")
    assert product["buy_url"].endswith("/18/39090?ref=735861")
    assert "сывороточный протеин" in product.get("composition", "")


def test_brain_coffee_description(descriptions_index: list[dict[str, object]]) -> None:
    product = _get_record(descriptions_index, "t8-era-brain-coffee")
    assert "кофе" in product["description"].lower()
    assert product["buy_url"].endswith("/25/23096?ref=735861")


def test_stekla_has_contra(descriptions_index: list[dict[str, object]]) -> None:
    product = _get_record(descriptions_index, "t8-stekla-black-96")
    assert product["buy_url"].endswith("/22/37416?ref=735861")
    assert product.get("usage") == "Надевать за 2 часа до сна."
    assert product.get("contra") == "Нет."
