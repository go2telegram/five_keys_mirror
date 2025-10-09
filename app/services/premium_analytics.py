"""Utilities for collecting Premium subscription analytics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Dict, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repo import events as events_repo, subscriptions as subscriptions_repo


_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_TWOPLACES = Decimal("0.01")


def _parse_price(value: str) -> Decimal:
    """Extract the numeric part of a price string."""

    if not value:
        return Decimal("0")
    normalized = value.replace(" ", "")
    match = _PRICE_RE.search(normalized)
    if not match:
        return Decimal("0")
    number = match.group(1).replace(",", ".")
    try:
        return Decimal(number)
    except InvalidOperation:
        return Decimal("0")


def _round_currency(value: Decimal) -> Decimal:
    return value.quantize(_TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class PremiumReport:
    generated_at: datetime
    plan_breakdown: Dict[str, int]
    active_subscriptions: int
    mrr: Decimal
    arppu: Decimal
    new_subscriptions_day: int
    churn_events_30d: int
    churn_rate: float
    ctr_cta: float
    events: Dict[str, int]

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["mrr"] = float(_round_currency(self.mrr))
        payload["arppu"] = float(_round_currency(self.arppu))
        payload["generated_at"] = self.generated_at
        payload["plan_breakdown"] = dict(self.plan_breakdown)
        payload["events"] = dict(self.events)
        return payload


def _plan_prices() -> Mapping[str, Decimal]:
    return {
        "basic": _parse_price(settings.SUB_BASIC_PRICE),
        "pro": _parse_price(settings.SUB_PRO_PRICE),
    }


async def collect_premium_report(session: AsyncSession) -> PremiumReport:
    now = datetime.now(timezone.utc)
    plan_counts_raw = await subscriptions_repo.count_active_by_plan(session)
    plan_breakdown: Dict[str, int] = {}
    for plan, count in plan_counts_raw.items():
        key = (plan or "unknown").lower()
        plan_breakdown[key] = plan_breakdown.get(key, 0) + int(count)

    active_total = sum(plan_breakdown.values())
    prices = _plan_prices()
    mrr = sum(prices.get(plan, Decimal("0")) * count for plan, count in plan_breakdown.items())
    arppu = Decimal("0")
    if active_total:
        arppu = mrr / Decimal(active_total)

    day_window = now - timedelta(days=1)
    churn_window = now - timedelta(days=30)

    new_day = await events_repo.stats(session, name="buy_success", since=day_window)
    churn_events = await events_repo.stats(session, name="subscription_cancelled", since=churn_window)

    churn_rate = 0.0
    if active_total:
        churn_rate = round((churn_events / active_total) * 100.0, 2)

    cta_shown = await events_repo.stats(session, name="cta_premium_shown")
    cta_clicked = await events_repo.stats(session, name="cta_premium_clicked")
    buy_started = await events_repo.stats(session, name="buy_started")
    buy_success = await events_repo.stats(session, name="buy_success")

    ctr_cta = 0.0
    if cta_shown:
        ctr_cta = round((cta_clicked / cta_shown) * 100.0, 2)

    return PremiumReport(
        generated_at=now,
        plan_breakdown=plan_breakdown,
        active_subscriptions=active_total,
        mrr=mrr,
        arppu=arppu,
        new_subscriptions_day=new_day,
        churn_events_30d=churn_events,
        churn_rate=churn_rate,
        ctr_cta=ctr_cta,
        events={
            "cta_premium_shown": cta_shown,
            "cta_premium_clicked": cta_clicked,
            "buy_started": buy_started,
            "buy_success": buy_success,
        },
    )

