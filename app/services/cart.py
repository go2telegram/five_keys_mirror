"""Shopping cart storage with optional Redis backend."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from threading import Thread
from typing import Any

from app.catalog.loader import product_by_alias, product_by_id
from app.storage import USE_REDIS

try:
    from app.storage_redis import cart_get, cart_pop, cart_set
except ImportError:  # pragma: no cover - redis optional
    cart_get = cart_set = cart_pop = None  # type: ignore[assignment]


if USE_REDIS and cart_get is not None:
    _redis_loop = asyncio.new_event_loop()

    def _redis_worker() -> None:  # pragma: no cover - background thread
        asyncio.set_event_loop(_redis_loop)
        _redis_loop.run_forever()

    Thread(target=_redis_worker, name="cart-redis", daemon=True).start()

    def _run_async(awaitable: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(awaitable, _redis_loop).result()

else:
    _redis_loop = None

    def _run_async(awaitable: Any) -> Any:  # pragma: no cover - no redis fallback
        return awaitable


@dataclass(slots=True)
class CartItem:
    product_id: str
    title: str
    price: Decimal = Decimal("0")
    quantity: int = 1
    currency: str = "RUB"
    utm: dict[str, str] = field(default_factory=dict)
    kind: str = "product"

    @property
    def subtotal(self) -> Decimal:
        return self.price * self.quantity

    def to_payload(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "title": self.title,
            "price": str(self.price),
            "quantity": self.quantity,
            "currency": self.currency,
            "utm": dict(self.utm),
            "kind": self.kind,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "CartItem":
        return cls(
            product_id=str(data.get("product_id")),
            title=str(data.get("title", "")),
            price=Decimal(str(data.get("price", "0"))),
            quantity=int(data.get("quantity", 1)),
            currency=str(data.get("currency", "RUB")),
            utm=dict(data.get("utm") or {}),
            kind=str(data.get("kind", "product")),
        )


@dataclass
class Cart:
    items: dict[str, CartItem] = field(default_factory=dict)
    coupon_code: str | None = None
    coupon_meta: dict[str, Any] = field(default_factory=dict)

    def add(self, item: CartItem) -> CartItem:
        existing = self.items.get(item.product_id)
        if existing:
            existing.quantity += item.quantity
            return existing
        self.items[item.product_id] = item
        return item

    def clear(self) -> None:
        self.items.clear()
        self.coupon_code = None
        self.coupon_meta.clear()

    @property
    def total(self) -> Decimal:
        return sum((item.subtotal for item in self.items.values()), start=Decimal("0"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "items": [item.to_payload() for item in self.items.values()],
            "coupon_code": self.coupon_code,
            "coupon_meta": dict(self.coupon_meta),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "Cart":
        items_payload = data.get("items") or []
        items: dict[str, CartItem] = {}
        for raw in items_payload:
            item = CartItem.from_payload(raw)
            items[item.product_id] = item
        cart = cls(items=items)
        cart.coupon_code = data.get("coupon_code")
        meta = data.get("coupon_meta") or {}
        cart.coupon_meta = dict(meta)
        return cart

    def summary_lines(self) -> list[str]:
        lines = []
        for item in self.items.values():
            price = f"{item.price:.2f} {item.currency}"
            lines.append(f"• {item.title} × {item.quantity} — {price}")
        total = self.total
        if self.coupon_code and self.coupon_meta.get("discount"):
            discount = Decimal(str(self.coupon_meta["discount"]))
            lines.append(f"Купон {self.coupon_code}: −{discount:.2f} {self.currency}")
            total -= discount
        lines.append(f"Итого: {total:.2f} {self.currency}")
        return lines

    @property
    def currency(self) -> str:
        for item in self.items.values():
            return item.currency
        return "RUB"


class CartStorage:
    """Hybrid cart store with optional Redis backend."""

    def __init__(self) -> None:
        self._local: dict[int, dict[str, Any]] = {}

    def _load(self, user_id: int) -> dict[str, Any] | None:
        if user_id in self._local:
            return self._local[user_id]
        if USE_REDIS and cart_get is not None:
            payload = _run_async(cart_get(user_id))
            if payload is not None:
                self._local[user_id] = payload
            return payload
        return None

    def _save(self, user_id: int, payload: dict[str, Any]) -> None:
        self._local[user_id] = payload
        if USE_REDIS and cart_set is not None:
            _run_async(cart_set(user_id, payload))

    def _delete(self, user_id: int) -> None:
        self._local.pop(user_id, None)
        if USE_REDIS and cart_pop is not None:
            _run_async(cart_pop(user_id))

    def get(self, user_id: int) -> Cart:
        payload = self._load(user_id)
        if payload is None:
            return Cart()
        return Cart.from_payload(payload)

    def set(self, user_id: int, cart: Cart) -> None:
        self._save(user_id, cart.to_payload())

    def clear(self, user_id: int) -> None:
        self._delete(user_id)


_CART = CartStorage()


def get_cart(user_id: int) -> Cart:
    return _CART.get(user_id)


def save_cart(user_id: int, cart: Cart) -> None:
    _CART.set(user_id, cart)


def clear_cart(user_id: int) -> None:
    _CART.clear(user_id)


def load_product(product_id: str) -> dict[str, Any] | None:
    product = product_by_id(product_id)
    if product:
        return dict(product)
    return product_by_alias(product_id)


def add_product_to_cart(user_id: int, product_id: str, *, quantity: int = 1) -> CartItem | None:
    product = load_product(product_id)
    if not product:
        return None
    order = product.get("order") or {}
    title = product.get("title") or product.get("name") or product_id
    raw_price = order.get("price") or product.get("price") or 0
    try:
        price = Decimal(str(raw_price))
    except Exception:  # pragma: no cover - guard against malformed price
        price = Decimal("0")
    currency = order.get("currency") or "RUB"
    utm = order.get("utm") or {}
    cart = get_cart(user_id)
    item = CartItem(
        product_id=product_id,
        title=title,
        price=price,
        quantity=quantity,
        currency=currency,
        utm={str(k): str(v) for k, v in utm.items()},
    )
    cart.add(item)
    save_cart(user_id, cart)
    return item


def add_bundle_to_cart(user_id: int, bundle: dict[str, Any]) -> CartItem:
    cart = get_cart(user_id)
    item = CartItem(
        product_id=f"bundle:{bundle['id']}",
        title=str(bundle.get("title", "Бандл")),
        price=Decimal(str(bundle.get("price", "0"))),
        quantity=1,
        kind="bundle",
    )
    cart.add(item)
    save_cart(user_id, cart)
    return item


__all__ = [
    "Cart",
    "CartItem",
    "add_product_to_cart",
    "add_bundle_to_cart",
    "clear_cart",
    "get_cart",
    "save_cart",
]
