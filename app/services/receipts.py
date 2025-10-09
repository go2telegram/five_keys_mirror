"""Receipt generation for orders."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.config import settings
from app.db.models import Order
from app.services.cart import Cart
from app.services.coupons import CouponResult

DEFAULT_RECEIPTS_DIR = Path(getattr(settings, "RECEIPTS_DIR", "/var/receipts"))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _format_currency(amount: Decimal | float, currency: str) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    return f"{value} {currency}"


def build_receipt_text(order: Order, cart: Cart, coupon: CouponResult | None) -> str:
    lines = [
        "MITO Bot — чек оплаты",
        f"Заказ #{order.id}",
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Состав заказа:",
    ]
    for item in cart.items.values():
        subtotal = _format_currency(item.subtotal, item.currency)
        lines.append(f"• {item.title} × {item.quantity} — {subtotal}")
    total = Decimal(str(order.amount))
    if coupon is not None:
        discount = _format_currency(coupon.discount, cart.currency)
        lines.append(f"Скидка ({coupon.coupon.code}): −{discount}")
    lines.append("")
    lines.append(f"Итого к оплате: {_format_currency(total, cart.currency)}")
    return "\n".join(lines)


def generate_receipt(
    order: Order,
    cart: Cart,
    coupon: CouponResult | None,
    *,
    directory: Optional[Path] = None,
) -> Path | None:
    base_dir = directory or DEFAULT_RECEIPTS_DIR
    try:
        _ensure_dir(base_dir)
    except Exception:  # pragma: no cover - fallback if directory not writable
        return None
    path = base_dir / f"order-{order.id}.txt"
    text = build_receipt_text(order, cart, coupon)
    path.write_text(text, encoding="utf-8")
    return path


__all__ = ["build_receipt_text", "generate_receipt"]
