from decimal import Decimal

from app.services.coupons import apply_coupon, is_coupon_valid


class DummyCoupon:
    def __init__(self, kind: str, amount: float, active: int = 1):
        self.kind = kind
        self.amount_or_pct = amount
        self.active = active
        self.valid_till = None
        self.code = "TEST"


def test_apply_coupon_percent():
    coupon = DummyCoupon("percent", 10)
    result = apply_coupon(Decimal("100"), coupon)  # type: ignore[arg-type]
    assert result.discount == Decimal("10")
    assert result.final_amount == Decimal("90")


def test_apply_coupon_fixed():
    coupon = DummyCoupon("fixed", 50)
    result = apply_coupon(Decimal("120"), coupon)  # type: ignore[arg-type]
    assert result.discount == Decimal("50")
    assert result.final_amount == Decimal("70")


def test_is_coupon_valid_checks_active():
    coupon = DummyCoupon("percent", 5, active=0)
    assert not is_coupon_valid(coupon)
