from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, Mapping

from app import storage


def _parse_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.min


def _safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


@dataclass(slots=True)
class BusinessMetrics:
    generated_at: datetime
    revenue: float
    acquisition_cost: float
    operating_cost: float
    ltv: float
    cac: float
    roi: float
    retention_rate: float
    customers_total: int
    customers_retained: int
    new_customers: int

    def as_dict(self) -> Mapping[str, float | int | str]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


def _latest_retention_status(events: Iterable[Mapping]) -> tuple[int, int]:
    latest: dict[int, tuple[datetime, bool]] = {}
    for event in events:
        user_id = event.get("user_id")
        if user_id is None:
            continue
        ts = _parse_ts(event.get("ts"))
        active = bool(event.get("active"))
        prev = latest.get(user_id)
        if prev is None or ts >= prev[0]:
            latest[user_id] = (ts, active)
    total = len(latest)
    retained = sum(1 for _, active in latest.values() if active)
    return total, retained


def collect_business_metrics() -> BusinessMetrics:
    revenue = 0.0
    operating_cost = 0.0
    customers_with_revenue: set[int] = set()

    for op in storage.FINANCE_OPERATIONS:
        amount = float(op.get("amount", 0.0))
        if op.get("type") == "revenue":
            revenue += amount
            user_id = op.get("user_id")
            if user_id is not None:
                customers_with_revenue.add(int(user_id))
        elif op.get("type") == "cost":
            operating_cost += amount

    acquisition_cost = 0.0
    new_customers: set[int] = set()
    for acquisition in storage.CUSTOMER_ACQUISITIONS:
        acquisition_cost += float(acquisition.get("cost", 0.0))
        user_id = acquisition.get("user_id")
        if user_id is not None:
            new_customers.add(int(user_id))

    total_retention, retained = _latest_retention_status(storage.RETENTION_EVENTS)

    customers_total = len(customers_with_revenue) or len(new_customers)
    ltv = _safe_div(revenue, customers_total)
    cac = _safe_div(acquisition_cost, len(new_customers))

    total_costs = acquisition_cost + operating_cost
    roi = _safe_div(revenue - total_costs, total_costs)
    retention_rate = _safe_div(retained, total_retention)

    return BusinessMetrics(
        generated_at=datetime.utcnow(),
        revenue=revenue,
        acquisition_cost=acquisition_cost,
        operating_cost=operating_cost,
        ltv=ltv,
        cac=cac,
        roi=roi,
        retention_rate=retention_rate,
        customers_total=customers_total,
        customers_retained=retained,
        new_customers=len(new_customers),
    )


def format_finance_report(metrics: BusinessMetrics) -> str:
    return (
        "💼 <b>Финансы</b>\n"
        f"Выручка: {metrics.revenue:,.2f} ₽\n"
        f"LTV: {metrics.ltv:,.2f} ₽\n"
        f"CAC: {metrics.cac:,.2f} ₽\n"
        f"ROI: {metrics.roi * 100:,.2f}%\n"
        f"Удержание: {metrics.retention_rate * 100:,.2f}%\n"
        f"Новых клиентов: {metrics.new_customers}\n"
        f"Активных клиентов: {metrics.customers_retained}/{metrics.customers_total}"
    )


def render_admin_dashboard(metrics: BusinessMetrics) -> str:
    body = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Business Analytics</title>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; }}
          h1 {{ font-size: 28px; margin-bottom: 16px; }}
          table {{ border-collapse: collapse; width: 420px; }}
          th, td {{ border: 1px solid #dde1e7; padding: 8px 12px; text-align: left; }}
          th {{ background: #f5f7fa; text-transform: uppercase; font-size: 12px; letter-spacing: .08em; color: #6b7280; }}
          td.value {{ font-weight: 600; }}
          caption {{ text-align: left; margin-bottom: 8px; color: #6b7280; font-size: 13px; }}
        </style>
      </head>
      <body>
        <h1>Business analytics</h1>
        <table>
          <caption>Снимок на {metrics.generated_at.isoformat()} UTC</caption>
          <tr><th>Метрика</th><th>Значение</th></tr>
          <tr><td>Выручка</td><td class="value">{metrics.revenue:,.2f} ₽</td></tr>
          <tr><td>LTV</td><td class="value">{metrics.ltv:,.2f} ₽</td></tr>
          <tr><td>CAC</td><td class="value">{metrics.cac:,.2f} ₽</td></tr>
          <tr><td>ROI</td><td class="value">{metrics.roi * 100:,.2f}%</td></tr>
          <tr><td>Удержание</td><td class="value">{metrics.retention_rate * 100:,.2f}%</td></tr>
          <tr><td>Новые клиенты</td><td class="value">{metrics.new_customers}</td></tr>
          <tr><td>Активные клиенты</td><td class="value">{metrics.customers_retained}/{metrics.customers_total}</td></tr>
          <tr><td>Маркетинг</td><td class="value">{metrics.acquisition_cost:,.2f} ₽</td></tr>
          <tr><td>Операционные расходы</td><td class="value">{metrics.operating_cost:,.2f} ₽</td></tr>
        </table>
      </body>
    </html>
    """
    return body


def render_prometheus(metrics: BusinessMetrics) -> str:
    return "\n".join([
        "# HELP business_revenue_total Total revenue in RUB",
        "# TYPE business_revenue_total gauge",
        f"business_revenue_total {metrics.revenue:.2f}",
        "# HELP business_ltv_average Average lifetime value in RUB",
        "# TYPE business_ltv_average gauge",
        f"business_ltv_average {metrics.ltv:.4f}",
        "# HELP business_cac_average Customer acquisition cost in RUB",
        "# TYPE business_cac_average gauge",
        f"business_cac_average {metrics.cac:.4f}",
        "# HELP business_roi Return on investment (ratio)",
        "# TYPE business_roi gauge",
        f"business_roi {metrics.roi:.6f}",
        "# HELP business_retention_rate Customer retention rate",
        "# TYPE business_retention_rate gauge",
        f"business_retention_rate {metrics.retention_rate:.6f}",
        "# HELP business_acquisition_cost_total Total acquisition spend in RUB",
        "# TYPE business_acquisition_cost_total gauge",
        f"business_acquisition_cost_total {metrics.acquisition_cost:.2f}",
        "# HELP business_operating_cost_total Total operating spend in RUB",
        "# TYPE business_operating_cost_total gauge",
        f"business_operating_cost_total {metrics.operating_cost:.2f}",
        "# HELP business_customers_total Number of paying customers",
        "# TYPE business_customers_total gauge",
        f"business_customers_total {metrics.customers_total}",
        "# HELP business_customers_retained Number of retained customers",
        "# TYPE business_customers_retained gauge",
        f"business_customers_retained {metrics.customers_retained}",
        "# HELP business_customers_new Number of new customers",
        "# TYPE business_customers_new gauge",
        f"business_customers_new {metrics.new_customers}",
    ]) + "\n"
