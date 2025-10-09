"""Checkout orchestration for the commerce stack."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CommerceSubscription, Order
from app.services.cart import Cart
from app.services.coupons import CouponResult, apply_coupon
from app.services.receipts import generate_receipt

DEFAULT_PROVIDER = "mock"
DEFAULT_CURRENCY = "RUB"


@dataclass(slots=True)
class CheckoutResult:
    order: Order
    coupon: CouponResult | None
    receipt_path: Path | None


async def _ensure_subscription(
    session: AsyncSession,
    *,
    user_id: int,
    plan: str,
    amount: Decimal,
    txn_id: str | None,
) -> CommerceSubscription:
    record = CommerceSubscription(
        user_id=user_id,
        plan=plan,
        amount=float(amount),
        txn_id=txn_id,
        status="active",
        started_at=datetime.now(timezone.utc),
    )
    session.add(record)
    await session.flush()
    return record


async def create_order(
    session: AsyncSession,
    *,
    user_id: int,
    cart: Cart,
    provider: str = DEFAULT_PROVIDER,
    coupon: CouponResult | None = None,
    subscription_plan: str | None = None,
    txn_id: str | None = None,
) -> CheckoutResult:
    amount = cart.total
    coupon_payload: dict[str, Any] = {}
    final_amount = amount
    if coupon is not None:
        coupon_payload = {
            "code": coupon.coupon.code,
            "kind": coupon.coupon.kind,
            "discount": str(coupon.discount),
        }
        final_amount = coupon.final_amount
    items_payload = cart.to_payload()["items"]
    utm_payload: dict[str, Any] = {}
    for item in cart.items.values():
        if item.utm:
            utm_payload.setdefault(item.product_id, {}).update(item.utm)

    order = Order(
        user_id=user_id,
        items_json={"items": items_payload},
        amount=float(final_amount),
        currency=cart.currency or DEFAULT_CURRENCY,
        status="paid",
        provider=provider,
        coupon_code=coupon_payload.get("code"),
        utm_json=utm_payload,
    )
    session.add(order)
    await session.flush()

    if subscription_plan:
        await _ensure_subscription(
            session,
            user_id=user_id,
            plan=subscription_plan,
            amount=final_amount,
            txn_id=txn_id,
        )

    receipt = generate_receipt(order, cart, coupon)
    return CheckoutResult(order=order, coupon=coupon, receipt_path=receipt)


async def calculate_total_with_coupon(cart: Cart, coupon) -> CouponResult | None:
    if coupon is None:
        return None
    amount = cart.total
    if amount <= 0:
        return None
    return apply_coupon(amount, coupon)


__all__ = ["CheckoutResult", "calculate_total_with_coupon", "create_order"]
