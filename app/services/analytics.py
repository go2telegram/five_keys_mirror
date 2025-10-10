"""Analytics helpers shared between CLI tools, commands and dashboard."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Event, User
from app.db.session import session_scope


@dataclass(slots=True)
class EventRecord:
    id: int
    ts: datetime
    user_id: int | None
    name: str
    meta: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.ts.isoformat(),
            "user_id": self.user_id,
            "event": self.name,
            "meta": self.meta,
        }


@dataclass(slots=True)
class FunnelStage:
    label: str
    event: str
    users: int
    conversion_from_previous: float
    conversion_from_start: float


@dataclass(slots=True)
class CohortRow:
    week_start: date
    size: int
    retention: list[float]


@dataclass(slots=True)
class CTRRow:
    product: str
    shows: int
    clicks: int
    ctr: float


@dataclass(slots=True)
class ExportResult:
    count: int
    csv_path: Path | None
    google_updated: bool
    clickhouse_inserted: bool


_DEFAULT_FUNNEL: Sequence[tuple[str, str]] = (
    ("Start", "start"),
    ("Tests", "quiz_finished"),
    ("Recommend", "reco_shown"),
    ("Cart", "reco_click_buy"),
    ("Checkout", "order_paid"),
    ("Paid", "premium_on"),
)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def default_range(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return since, now


async def load_event_records(
    session: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
    names: Sequence[str] | None = None,
) -> list[EventRecord]:
    stmt = select(Event).order_by(Event.ts.asc())
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    if until is not None:
        stmt = stmt.where(Event.ts < until)
    if names:
        stmt = stmt.where(Event.name.in_(names))
    result = await session.execute(stmt)
    events = result.scalars().all()
    return [
        EventRecord(
            id=event.id,
            ts=_ensure_aware(event.ts),
            user_id=event.user_id,
            name=event.name,
            meta=dict(event.meta or {}),
        )
        for event in events
    ]


async def funnel_stats(
    session: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
    stages: Sequence[tuple[str, str]] = _DEFAULT_FUNNEL,
) -> list[FunnelStage]:
    seen_users: dict[str, set[int]] = {}
    for _, event_name in stages:
        stmt = select(Event.user_id).where(Event.name == event_name, Event.user_id.is_not(None))
        if since is not None:
            stmt = stmt.where(Event.ts >= since)
        if until is not None:
            stmt = stmt.where(Event.ts < until)
        rows = await session.execute(stmt)
        seen_users[event_name] = {int(row[0]) for row in rows if row[0] is not None}

    stages_data: list[FunnelStage] = []
    start_total = len(seen_users.get(stages[0][1], set())) if stages else 0
    previous_total = None
    for label, event_name in stages:
        users = len(seen_users.get(event_name, set()))
        if previous_total is None:
            conv_prev = 0.0
        elif previous_total == 0:
            conv_prev = 0.0
        else:
            conv_prev = users / previous_total * 100.0
        conv_start = (users / start_total * 100.0) if start_total else 0.0
        stages_data.append(
            FunnelStage(
                label=label,
                event=event_name,
                users=users,
                conversion_from_previous=round(conv_prev, 2),
                conversion_from_start=round(conv_start, 2),
            )
        )
        previous_total = users
    return stages_data


def render_funnel_report(stages: Iterable[FunnelStage]) -> str:
    lines = ["📈 <b>Воронка</b>", "Этап | Пользователи | Конверсия от пред. | Конверсия от старта"]
    for stage in stages:
        lines.append(
            f"{stage.label}: <b>{stage.users}</b> — {stage.conversion_from_previous:.1f}% → {stage.conversion_from_start:.1f}%"
        )
    return "\n".join(lines)


async def cohort_retention(
    session: AsyncSession,
    weeks: int = 8,
    event_names: Sequence[str] | None = None,
) -> list[CohortRow]:
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(weeks=weeks)).date()
    start_week = start_date - timedelta(days=start_date.weekday())
    start_dt = datetime.combine(start_week, datetime.min.time(), tzinfo=timezone.utc)

    stmt_users = select(User.id, User.created).where(User.created >= start_dt).order_by(User.created.asc())
    user_rows = await session.execute(stmt_users)
    cohorts: dict[date, set[int]] = {}
    user_created: dict[int, date] = {}
    for user_id, created in user_rows:
        if user_id is None or created is None:
            continue
        created_at = _ensure_aware(created)
        week_start = created_at.date() - timedelta(days=created_at.date().weekday())
        if week_start < start_week:
            continue
        cohorts.setdefault(week_start, set()).add(int(user_id))
        user_created[int(user_id)] = week_start

    if not user_created:
        return []

    relevant_user_ids = list(user_created.keys())
    stmt_events = (
        select(Event.user_id, Event.ts)
        .where(Event.user_id.in_(relevant_user_ids))
        .where(Event.ts >= start_dt)
    )
    if event_names:
        stmt_events = stmt_events.where(Event.name.in_(event_names))
    event_rows = await session.execute(stmt_events)

    retention: dict[date, dict[int, set[int]]] = {}
    for user_id, ts in event_rows:
        if user_id is None or ts is None:
            continue
        created_week = user_created.get(int(user_id))
        if created_week is None:
            continue
        ts_aware = _ensure_aware(ts)
        week_offset = (ts_aware.date() - created_week).days // 7
        if week_offset <= 0:
            continue
        bucket = retention.setdefault(created_week, {})
        week_bucket = bucket.setdefault(week_offset, set())
        week_bucket.add(int(user_id))

    rows: list[CohortRow] = []
    for week in sorted(cohorts.keys()):
        cohort_users = cohorts[week]
        size = len(cohort_users)
        if size == 0:
            continue
        weeks_retention: list[float] = []
        bucket = retention.get(week, {})
        for offset in range(1, weeks + 1):
            active_users = len(bucket.get(offset, set()))
            weeks_retention.append(round(active_users / size * 100.0, 2))
        rows.append(CohortRow(week_start=week, size=size, retention=weeks_retention))
    return rows


def render_cohort_report(rows: Iterable[CohortRow]) -> str:
    lines = ["📊 <b>Когортный ретеншн</b>"]
    if not rows:
        lines.append("Недостаточно данных для расчёта ретеншна.")
        return "\n".join(lines)
    header = "Неделя | Новых | +1 | +2 | +3 | +4"
    lines.append(header)
    for row in rows:
        week_label = row.week_start.strftime("%Y-%m-%d")
        points = " | ".join(f"{value:.1f}%" for value in row.retention[:4])
        lines.append(f"{week_label} | {row.size} | {points}")
    return "\n".join(lines)


async def ctr_stats(
    session: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 10,
) -> list[CTRRow]:
    shows_counter: dict[str, int] = {}
    clicks_counter: dict[str, int] = {}

    stmt_shows = select(Event.meta).where(Event.name == "reco_shown")
    if since is not None:
        stmt_shows = stmt_shows.where(Event.ts >= since)
    if until is not None:
        stmt_shows = stmt_shows.where(Event.ts < until)
    for meta in (await session.execute(stmt_shows)).scalars():
        payload = meta or {}
        for code in payload.get("products", []) or []:
            if code:
                key = str(code)
                shows_counter[key] = shows_counter.get(key, 0) + 1

    stmt_clicks = select(Event.meta).where(Event.name == "reco_click_buy")
    if since is not None:
        stmt_clicks = stmt_clicks.where(Event.ts >= since)
    if until is not None:
        stmt_clicks = stmt_clicks.where(Event.ts < until)
    for meta in (await session.execute(stmt_clicks)).scalars():
        payload = meta or {}
        code = payload.get("product")
        if code:
            key = str(code)
            clicks_counter[key] = clicks_counter.get(key, 0) + 1

    rows: list[CTRRow] = []
    for product, shows in sorted(shows_counter.items(), key=lambda item: item[1], reverse=True):
        clicks = clicks_counter.get(product, 0)
        ctr_value = (clicks / shows * 100.0) if shows else 0.0
        rows.append(CTRRow(product=product, shows=shows, clicks=clicks, ctr=round(ctr_value, 2)))
        if len(rows) >= limit:
            break

    return rows


def render_ctr_report(rows: Iterable[CTRRow]) -> str:
    lines = ["🎯 <b>CTR рекомендаций</b>", "Продукт | Показы | Клики | CTR"]
    if not rows:
        lines.append("Данных пока нет.")
        return "\n".join(lines)
    for row in rows:
        lines.append(f"{row.product}: {row.shows} → {row.clicks} ({row.ctr:.1f}%)")
    return "\n".join(lines)


def _write_events_csv(rows: Sequence[EventRecord], directory: Path, day: date) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = directory / f"events_{day.strftime('%Y%m%d')}.csv"
    with filename.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["id", "timestamp", "user_id", "event", "meta_json"])
        for row in rows:
            writer.writerow(
                [
                    row.id,
                    row.ts.isoformat(),
                    row.user_id or "",
                    row.name,
                    json.dumps(row.meta, ensure_ascii=False),
                ]
            )
    return filename


async def _export_google(rows: Sequence[EventRecord], sheet_id: str, worksheet_title: str) -> bool:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:  # pragma: no cover - optional dependency
        raise RuntimeError("gspread and google-auth must be installed for Google Sheets export")

    creds_payload = os.getenv("GOOGLE_SERVICE_ACCOUNT_INFO") or settings.GOOGLE_SERVICE_ACCOUNT_INFO
    credentials: Credentials
    if creds_payload:
        info = json.loads(creds_payload)
        credentials = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    else:
        file_value = (
            os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            or settings.GOOGLE_SERVICE_ACCOUNT_FILE
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )
        if not file_value:
            raise RuntimeError("Google service account credentials are not configured")
        credentials = Credentials.from_service_account_file(str(file_value), scopes=["https://www.googleapis.com/auth/spreadsheets"])

    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_title, rows="100", cols="8")

    payload = [
        [row.id, row.ts.isoformat(), row.user_id or "", row.name, json.dumps(row.meta, ensure_ascii=False)]
        for row in rows
    ]
    worksheet.clear()
    if payload:
        worksheet.update("A1", [["id", "timestamp", "user_id", "event", "meta"]] + payload)
    else:
        worksheet.update("A1", [["id", "timestamp", "user_id", "event", "meta"]])
    return True


async def _export_clickhouse(rows: Sequence[EventRecord], url: str, table: str) -> bool:
    if not rows:
        return False
    payload = "\n".join(json.dumps(row.as_dict(), ensure_ascii=False) for row in rows)
    query = f"INSERT INTO {table} FORMAT JSONEachRow"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, params={"query": query}, content=payload.encode("utf-8"))
        response.raise_for_status()
    return True


async def export_events_range(
    since: datetime,
    until: datetime,
    *,
    csv_dir: Path | None = None,
    sheet_id: str | None = None,
    worksheet_title: str | None = None,
    clickhouse_url: str | None = None,
    clickhouse_table: str | None = None,
) -> ExportResult:
    async with session_scope() as session:
        rows = await load_event_records(session, since, until)

    csv_path: Path | None = None
    google_ok = False
    clickhouse_ok = False

    if csv_dir is not None:
        csv_path = _write_events_csv(rows, csv_dir, since.date())

    if sheet_id and worksheet_title:
        try:
            google_ok = await _export_google(rows, sheet_id, worksheet_title)
        except Exception:
            google_ok = False

    if clickhouse_url and clickhouse_table:
        try:
            clickhouse_ok = await _export_clickhouse(rows, clickhouse_url, clickhouse_table)
        except Exception:
            clickhouse_ok = False

    return ExportResult(count=len(rows), csv_path=csv_path, google_updated=google_ok, clickhouse_inserted=clickhouse_ok)
