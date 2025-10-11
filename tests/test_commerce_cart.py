from decimal import Decimal

import pytest

from app.services.cart import add_product_to_cart, clear_cart, get_cart


@pytest.mark.parametrize("product_id", ["t8-beet-shot", "t8-blend-90"])
def test_add_product_to_cart_roundtrip(product_id):
    user_id = 4242
    clear_cart(user_id)
    item = add_product_to_cart(user_id, product_id)
    assert item is not None
    cart = get_cart(user_id)
    assert product_id in cart.items
    stored = cart.items[product_id]
    assert stored.title
    assert stored.quantity == 1
    assert isinstance(stored.price, Decimal)
    clear_cart(user_id)


def test_cart_summary_includes_coupon(monkeypatch):
    user_id = 5252
    clear_cart(user_id)
    add_product_to_cart(user_id, "t8-beet-shot")
    cart = get_cart(user_id)
    cart.coupon_code = "TEST"
    cart.coupon_meta = {"discount": "10"}
    lines = cart.summary_lines()
    assert any("Купон TEST" in line for line in lines)
    assert any("Итого" in line for line in lines)
    clear_cart(user_id)
