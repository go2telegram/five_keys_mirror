"""Coupon helpers for commerce flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Coupon


@dataclass(slots=True)
class CouponResult:
    coupon: Coupon
    discount: Decimal
    final_amount: Decimal


async def fetch_coupon(session: AsyncSession, code: str) -> Coupon | None:
    normalized = code.strip().upper()
    if not normalized:
        return None
    coupon = await session.get(Coupon, normalized)
    return coupon


def is_coupon_valid(coupon: Coupon | None) -> bool:
    if coupon is None:
        return False
    if not coupon.active:
        return False
    if coupon.valid_till is not None:
        now = datetime.now(timezone.utc)
        if coupon.valid_till < now:
            return False
    return True


def apply_coupon(amount: Decimal, coupon: Coupon) -> CouponResult:
    amount = max(amount, Decimal("0"))
    kind = (coupon.kind or "").lower()
    raw = Decimal(str(coupon.amount_or_pct))
    discount = Decimal("0")
    if kind in {"percent", "percentage", "pct"}:
        discount = (amount * raw) / Decimal("100")
    elif kind in {"fixed", "amount"}:
        discount = raw
    discount = min(max(discount, Decimal("0")), amount)
    final = amount - discount
    return CouponResult(coupon=coupon, discount=discount, final_amount=final)


__all__ = ["CouponResult", "apply_coupon", "fetch_coupon", "is_coupon_valid"]
