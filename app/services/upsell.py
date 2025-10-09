"""Helpers that provide soft upsell prompts for product cards."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from app.db.session import compat_session, session_scope
from app.services.bundles import suggest_bundle


async def soft_upsell_prompt(product_codes: Iterable[str]) -> tuple[str | None, int | None]:
    codes = [code for code in product_codes if code]
    if not codes:
        return None, None
    async with compat_session(session_scope) as session:
        bundle = await suggest_bundle(session, codes)
    if bundle is None:
        return None, None
    price = Decimal(str(getattr(bundle, "price", 0)))
    discount = (price * Decimal("0.2")).quantize(Decimal("1"))
    text = f"🎁 Добавьте «{bundle.title}» со скидкой {discount} ₽"
    return text, bundle.id


__all__ = ["soft_upsell_prompt"]
