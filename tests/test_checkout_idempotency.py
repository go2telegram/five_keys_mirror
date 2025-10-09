from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import checkout
from app.services.cart import Cart, CartItem


@pytest.mark.asyncio
async def test_create_order_returns_existing(monkeypatch):
    cart = Cart()
    cart.add(CartItem(product_id="p1", title="Test", price=Decimal("10")))

    existing_order = SimpleNamespace(items_json={"items": []}, amount=10.0, currency="RUB")

    async def fake_find(session, *, user_id: int, provider: str, txn_id: str):
        return existing_order

    monkeypatch.setattr(checkout, "_find_existing_order", fake_find)
    monkeypatch.setattr(checkout, "generate_receipt", lambda *_args, **_kwargs: Path("receipt.txt"))

    session = AsyncMock()
    session.add = AsyncMock()
    session.flush = AsyncMock()

    result = await checkout.create_order(
        session,
        user_id=42,
        cart=cart,
        provider="telegram",
        txn_id="txn-1",
    )

    assert result.order is existing_order
    session.add.assert_not_awaited()
    session.flush.assert_not_awaited()
