"""Checkout orchestration for the commerce stack."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
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


async def _find_existing_order(
    session: AsyncSession,
    *,
    user_id: int,
    provider: str,
    txn_id: str,
) -> Order | None:
    """Return the latest order with the same ``txn_id`` if it exists."""

    stmt = select(Order).where(Order.user_id == user_id, Order.provider == provider).order_by(Order.id.desc()).limit(20)
    result = await session.execute(stmt)
    for record in result.scalars():
        payload = record.items_json or {}
        if isinstance(payload, dict):
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if payload.get("txn_id") == txn_id or meta.get("txn_id") == txn_id:
                return record
    return None


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
    if txn_id:
        existing = await _find_existing_order(
            session,
            user_id=user_id,
            provider=provider,
            txn_id=txn_id,
        )
        if existing is not None:
            receipt = generate_receipt(existing, cart, coupon)
            return CheckoutResult(order=existing, coupon=coupon, receipt_path=receipt)

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
    items_json: dict[str, Any] = {"items": items_payload}
    if txn_id:
        items_json["txn_id"] = txn_id
        items_json.setdefault("meta", {})
        if isinstance(items_json["meta"], dict):
            items_json["meta"]["txn_id"] = txn_id
    utm_payload: dict[str, Any] = {}
    for item in cart.items.values():
        if item.utm:
            utm_payload.setdefault(item.product_id, {}).update(item.utm)
    if txn_id:
        utm_payload.setdefault("__meta", {})
        if isinstance(utm_payload["__meta"], dict):
            utm_payload["__meta"]["txn_id"] = txn_id

    order = Order(
        user_id=user_id,
        items_json=items_json,
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
