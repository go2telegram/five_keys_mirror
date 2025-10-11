"""Premium analytics helpers used by admin commands."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PremiumSubscription:
    """A subscription sample used for analytics calculations."""

    user_id: int
    plan: str
    started: dt.datetime
    until: dt.datetime
    price: float
    period_days: int = 30

    def monthly_value(self) -> float:
        if self.period_days <= 0:
            return self.price
        return self.price * (30 / self.period_days)

    def is_active(self, as_of: dt.datetime) -> bool:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=dt.timezone.utc)
        start = self.started if self.started.tzinfo else self.started.replace(tzinfo=dt.timezone.utc)
        end = self.until if self.until.tzinfo else self.until.replace(tzinfo=dt.timezone.utc)
        return start <= as_of < end


@dataclass(frozen=True, slots=True)
class PremiumFunnel:
    shows: int = 0
    clicks: int = 0
    buy_started: int = 0
    buy_success: int = 0

    def ctr(self) -> float:
        return self.clicks / self.shows if self.shows else 0.0

    def conversion(self) -> float:
        return self.buy_success / self.buy_started if self.buy_started else 0.0


@dataclass(slots=True)
class PremiumReport:
    generated_at: dt.datetime
    mrr: float
    active_subs: int
    new_subs_per_day: Mapping[dt.date, int]
    churn_rate: float
    arppu: float
    funnel: PremiumFunnel

    def as_text(self) -> str:
        lines = ["💎 Premium аналитика"]
        lines.append(f"MRR: {self.mrr:.2f} ₽")
        lines.append(f"Активных подписок: {self.active_subs}")
        if self.new_subs_per_day:
            newest = ", ".join(f"{day:%d.%m}: {count}" for day, count in sorted(self.new_subs_per_day.items()))
            lines.append(f"Новые/день: {newest}")
        else:
            lines.append("Новые/день: нет данных")
        lines.append(f"Churn: {self.churn_rate:.2%}")
        lines.append(f"ARPPU: {self.arppu:.2f} ₽")
        lines.append(f"CTR CTA: {self.funnel.ctr():.1%}")
        lines.append(f"Conversion: {self.funnel.conversion():.1%}")
        return "\n".join(lines)


def build_premium_report(
    subscriptions: Iterable[PremiumSubscription],
    funnel: PremiumFunnel,
    as_of: dt.datetime | None = None,
    window: dt.timedelta = dt.timedelta(days=30),
) -> PremiumReport:
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=dt.timezone.utc)

    subs = list(subscriptions)
    active = [sub for sub in subs if sub.is_active(as_of)]
    mrr = sum(sub.monthly_value() for sub in active)

    window_start = as_of - window
    new_subs: dict[dt.date, int] = {}
    churn_events = 0
    revenue_total = 0.0
    paying_users: set[int] = set()

    for sub in subs:
        start = sub.started if sub.started.tzinfo else sub.started.replace(tzinfo=dt.timezone.utc)
        end = sub.until if sub.until.tzinfo else sub.until.replace(tzinfo=dt.timezone.utc)
        revenue_total += sub.price
        paying_users.add(sub.user_id)
        if window_start <= start <= as_of:
            day = start.date()
            new_subs[day] = new_subs.get(day, 0) + 1
        if window_start <= end <= as_of:
            churn_events += 1

    base = max(len(active) + churn_events, 1)
    churn_rate = churn_events / base
    arppu = revenue_total / len(paying_users) if paying_users else 0.0

    return PremiumReport(
        generated_at=as_of,
        mrr=mrr,
        active_subs=len(active),
        new_subs_per_day=new_subs,
        churn_rate=churn_rate,
        arppu=arppu,
        funnel=funnel,
    )
