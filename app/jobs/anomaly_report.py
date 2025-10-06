from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Sequence

import httpx
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.analytics.anomaly import Anomaly, TimeSeries, detect, report as render_report
from app.config import settings
from app.metrics import ANOMALY_ACTIVE

WINDOW_DELTAS = {
    "1h": dt.timedelta(hours=1),
    "24h": dt.timedelta(hours=24),
}


@dataclass(slots=True)
class MetricSpec:
    slug: str
    display: str
    query_template: str
    windows: tuple[str, ...] = ("1h", "24h")
    scale: float = 1.0

    def query(self, window: str) -> str:
        return self.query_template.format(window=window)


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        slug="handler_latency",
        display="Handler latency P95 (ms)",
        query_template=(
            "histogram_quantile(0.95, sum(rate(handler_latency_seconds_bucket[{window}])) by (le)) * 1000"
        ),
    ),
    MetricSpec(
        slug="handler_errors_total",
        display="Handler errors (count)",
        query_template="sum(increase(handler_errors_total[{window}]))",
    ),
    MetricSpec(
        slug="rps",
        display="Requests per second",
        query_template="sum(rate(handler_requests_total[{window}]))",
    ),
)

ALL_KINDS = tuple(f"{spec.slug}:{window}" for spec in METRIC_SPECS for window in spec.windows)
for kind in ALL_KINDS:
    try:
        ANOMALY_ACTIVE.labels(kind=kind).set(0)
    except ValueError:
        # метка уже зарегистрирована — игнорируем
        pass


@dataclass(slots=True)
class AnalysisResult:
    anomalies: list[Anomaly]
    active_kinds: set[str]
    errors: list[str]


_PREVIOUS_ACTIVE: set[str] = set()
_LAST_ALERT_AT: dict[str, dt.datetime] = {}


def _format_ts(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _step_for(window: str) -> str:
    if window == "1h":
        return "60"
    if window == "24h":
        return "300"
    seconds = max(60, int(WINDOW_DELTAS.get(window, dt.timedelta(minutes=5)).total_seconds() / 120))
    return str(seconds)


async def _fetch_timeseries(
    client: httpx.AsyncClient, spec: MetricSpec, window: str
) -> tuple[TimeSeries | None, str | None]:
    delta = WINDOW_DELTAS.get(window)
    if not delta:
        return None, f"Unknown window {window}"

    end = dt.datetime.now(dt.timezone.utc)
    start = end - delta
    params = {
        "query": spec.query(window),
        "start": _format_ts(start),
        "end": _format_ts(end),
        "step": _step_for(window),
    }

    try:
        response = await client.get("/api/v1/query_range", params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return None, f"HTTP error for {spec.slug}/{window}: {exc}"

    payload = response.json()
    if payload.get("status") != "success":
        error_type = payload.get("errorType", "unknown")
        error_text = payload.get("error", "")
        return None, f"Prometheus error for {spec.slug}/{window}: {error_type} {error_text}".strip()

    result = payload.get("data", {}).get("result", [])
    if not result:
        return TimeSeries(slug=spec.slug, name=spec.display, points=[]), None

    aggregated: dict[dt.datetime, list[float]] = {}
    for row in result:
        for ts_raw, value_raw in row.get("values", []):
            try:
                ts = dt.datetime.fromtimestamp(float(ts_raw), tz=dt.timezone.utc)
                value = float(value_raw) * spec.scale
            except Exception:
                continue
            if not math.isfinite(value):
                continue
            aggregated.setdefault(ts, []).append(value)

    points = sorted(
        (ts, sum(values) / len(values)) for ts, values in aggregated.items()
    )
    return TimeSeries(slug=spec.slug, name=spec.display, points=points), None


async def _analyse() -> AnalysisResult:
    if not settings.PROMETHEUS_URL:
        return AnalysisResult([], set(), ["PROMETHEUS_URL is not configured"])

    anomalies: list[Anomaly] = []
    active: set[str] = set()
    errors: list[str] = []

    base_url = settings.PROMETHEUS_URL.rstrip("/")
    headers: dict[str, str] = {}
    if settings.PROMETHEUS_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {settings.PROMETHEUS_BEARER_TOKEN}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=15.0) as client:
        for spec in METRIC_SPECS:
            for window in spec.windows:
                kind = f"{spec.slug}:{window}"
                series, error = await _fetch_timeseries(client, spec, window)
                if error:
                    errors.append(error)
                if series is None:
                    ANOMALY_ACTIVE.labels(kind=kind).set(0)
                    continue
                if not series.points:
                    ANOMALY_ACTIVE.labels(kind=kind).set(0)
                    continue
                detected = detect(series, window=window)
                if detected:
                    anomalies.extend(detected)
                    active.add(kind)
                    ANOMALY_ACTIVE.labels(kind=kind).set(1)
                else:
                    ANOMALY_ACTIVE.labels(kind=kind).set(0)

    return AnalysisResult(anomalies=anomalies, active_kinds=active, errors=errors)


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in settings.admin_chat_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:  # noqa: BLE001 — логируем и продолжаем
            print(f"[anomaly] failed to notify admin {admin_id}: {exc}")


def _render_errors(errors: Sequence[str]) -> str:
    if not errors:
        return ""
    return "\n\n⚠️ " + "; ".join(errors)


async def send_daily_anomaly_report(bot: Bot) -> None:
    result = await _analyse()
    text = render_report(result.anomalies) + _render_errors(result.errors)
    await _notify_admins(bot, text)


def _format_latency_alert(anomaly: Anomaly) -> str:
    change = anomaly.change_pct or 0.0
    baseline = f"{anomaly.baseline:.2f}"
    current = f"{anomaly.value:.2f}"
    ts = anomaly.timestamp.strftime("%Y-%m-%d %H:%M")
    return (
        "🚨 High latency detected\n"
        f"{anomaly.metric} ({anomaly.window}) ↑ {change:+.1f}% → {current} (baseline {baseline})\n"
        f"z={anomaly.z_score:.1f} @ {ts} UTC"
    )


async def monitor_anomalies(bot: Bot) -> None:
    global _PREVIOUS_ACTIVE

    result = await _analyse()
    now = dt.datetime.now(dt.timezone.utc)
    active = result.active_kinds
    new_kinds = active - _PREVIOUS_ACTIVE
    _PREVIOUS_ACTIVE = set(active)

    for anomaly in result.anomalies:
        if anomaly.slug != "handler_latency":
            continue
        if anomaly.direction != "up":
            continue
        pct = anomaly.change_pct or 0.0
        if pct < 30.0:
            continue
        if anomaly.timestamp < now - dt.timedelta(minutes=10):
            continue
        kind = anomaly.kind
        last_alert = _LAST_ALERT_AT.get(kind)
        if kind not in new_kinds and last_alert and (now - last_alert) < dt.timedelta(minutes=30):
            continue
        _LAST_ALERT_AT[kind] = now
        message = _format_latency_alert(anomaly) + _render_errors(result.errors)
        await _notify_admins(bot, message)


async def get_anomaly_report() -> tuple[str, list[Anomaly]]:
    result = await _analyse()
    text = render_report(result.anomalies) + _render_errors(result.errors)
    return text, result.anomalies


def register_anomaly_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    if not settings.PROMETHEUS_URL:
        print("[anomaly] PROMETHEUS_URL is not set — anomaly jobs disabled")
        return

    scheduler.add_job(
        send_daily_anomaly_report,
        trigger=CronTrigger(hour=9, minute=0),
        args=[bot],
        name="anomaly_daily_report",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        monitor_anomalies,
        trigger=IntervalTrigger(minutes=5),
        args=[bot],
        name="anomaly_monitor",
        misfire_grace_time=120,
        coalesce=True,
        max_instances=1,
    )
