"""Export CRM data (leads, quizzes, recommendations) to CSV or Google Sheets."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db.models import Lead
from app.db.session import session_scope
from app.repo import events as events_repo

_HEADERS = [
    "lead_id",
    "user_id",
    "username",
    "name",
    "phone",
    "comment",
    "lead_created_at",
    "quiz_type",
    "quiz_score",
    "quiz_level",
    "quiz_completed_at",
    "recommendation_title",
    "recommendation_context",
    "recommendation_level",
    "recommendation_created_at",
    "recommended_products",
    "recommendation_order_url",
]
_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@dataclass(slots=True)
class LeadExportRow:
    lead_id: int
    user_id: int | None
    username: str | None
    name: str
    phone: str
    comment: str | None
    lead_created_at: datetime
    quiz_type: str | None
    quiz_score: Any
    quiz_level: Any
    quiz_completed_at: datetime | None
    recommendation_title: str | None
    recommendation_context: str | None
    recommendation_level: Any
    recommendation_created_at: datetime | None
    recommended_products: list[str]
    recommendation_order_url: str | None

    def as_row(self) -> list[str]:
        def _fmt(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat(timespec="seconds")
            return str(value)

        return [
            str(self.lead_id),
            _fmt(self.user_id),
            _fmt(self.username),
            self.name,
            self.phone,
            _fmt(self.comment),
            _fmt(self.lead_created_at),
            _fmt(self.quiz_type),
            _fmt(self.quiz_score),
            _fmt(self.quiz_level),
            _fmt(self.quiz_completed_at),
            _fmt(self.recommendation_title),
            _fmt(self.recommendation_context),
            _fmt(self.recommendation_level),
            _fmt(self.recommendation_created_at),
            ", ".join(self.recommended_products),
            _fmt(self.recommendation_order_url),
        ]


async def _load_leads(session: AsyncSession) -> Sequence[Lead]:
    stmt = select(Lead).order_by(Lead.ts.desc(), Lead.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars())


async def _build_rows() -> list[LeadExportRow]:
    async with session_scope() as session:
        try:
            leads = await _load_leads(session)
        except SQLAlchemyError as exc:
            print(f"[crm-export] database access failed: {exc}")
            leads = []
            quiz_events = {}
            plan_events = {}
        else:
            user_ids = {lead.user_id for lead in leads if lead.user_id is not None}
            quiz_events = await events_repo.latest_by_users(session, "quiz_finish", user_ids)
            plan_events = await events_repo.latest_by_users(session, "plan_generated", user_ids)

    rows: list[LeadExportRow] = []
    for lead in leads:
        quiz_event = quiz_events.get(lead.user_id) if lead.user_id is not None else None
        plan_event = plan_events.get(lead.user_id) if lead.user_id is not None else None
        quiz_meta = quiz_event.meta if quiz_event is not None else {}
        plan_meta = plan_event.meta if plan_event is not None else {}
        rows.append(
            LeadExportRow(
                lead_id=lead.id,
                user_id=lead.user_id,
                username=lead.username,
                name=lead.name,
                phone=lead.phone,
                comment=lead.comment,
                lead_created_at=lead.ts,
                quiz_type=quiz_meta.get("quiz"),
                quiz_score=quiz_meta.get("score"),
                quiz_level=quiz_meta.get("level"),
                quiz_completed_at=getattr(quiz_event, "ts", None),
                recommendation_title=plan_meta.get("title"),
                recommendation_context=plan_meta.get("context"),
                recommendation_level=plan_meta.get("level"),
                recommendation_created_at=getattr(plan_event, "ts", None),
                recommended_products=[str(item) for item in plan_meta.get("products", []) if item],
                recommendation_order_url=(plan_meta.get("order_url") or plan_meta.get("order")),
            )
        )
    return rows


def _write_csv(rows: Iterable[LeadExportRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(_HEADERS)
        for row in rows:
            writer.writerow(row.as_row())
    return path


def _export_google(rows: Iterable[LeadExportRow], sheet_id: str, worksheet_title: str) -> None:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("gspread and google-auth must be installed for Google export") from exc

    creds_payload = os.getenv("GOOGLE_SERVICE_ACCOUNT_INFO") or settings.GOOGLE_SERVICE_ACCOUNT_INFO
    credentials: Credentials
    if creds_payload:
        info = json.loads(creds_payload)
        credentials = Credentials.from_service_account_info(info, scopes=_GOOGLE_SCOPES)
    else:
        file_path = (
            os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            or settings.GOOGLE_SERVICE_ACCOUNT_FILE
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )
        if not file_path:
            raise RuntimeError("Google service account credentials are not configured")
        credentials = Credentials.from_service_account_file(file_path, scopes=_GOOGLE_SCOPES)

    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_title, rows="100", cols=str(len(_HEADERS) + 5))

    payload = [row.as_row() for row in rows]
    worksheet.clear()
    if payload:
        worksheet.update("A1", [_HEADERS] + payload)
    else:
        worksheet.update("A1", [_HEADERS])


def _summarize(rows: Sequence[LeadExportRow]) -> str:
    total_leads = len(rows)
    with_quiz = sum(1 for row in rows if row.quiz_type)
    with_plan = sum(1 for row in rows if row.recommendation_title)
    products = Counter(code for row in rows for code in row.recommended_products)
    top_products = ", ".join(f"{code}×{count}" for code, count in products.most_common(5))
    return (
        f"leads={total_leads}, quizzes={with_quiz}, recommendations={with_plan}, "
        f"top_products=[{top_products}]"
    )


async def run() -> None:
    rows = await _build_rows()
    mode = (os.getenv("CRM_EXPORT_MODE") or settings.CRM_EXPORT_MODE or "csv").lower()

    if mode not in {"csv", "google"}:
        raise SystemExit(f"Unsupported CRM_EXPORT_MODE: {mode}")

    if mode == "csv":
        csv_path = Path(os.getenv("CRM_EXPORT_CSV_PATH") or settings.CRM_EXPORT_CSV_PATH)
        path = _write_csv(rows, csv_path)
        print(f"[crm-export] wrote {len(rows)} rows to {path} ({_summarize(rows)})")
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID") or settings.GOOGLE_SHEET_ID
    if not sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID is required for Google Sheets export")
    worksheet_title = os.getenv("GOOGLE_WORKSHEET_TITLE") or settings.GOOGLE_WORKSHEET_TITLE
    _export_google(rows, sheet_id, worksheet_title)
    print(f"[crm-export] pushed {len(rows)} rows to Google Sheet {sheet_id}/{worksheet_title} ({_summarize(rows)})")


if __name__ == "__main__":
    asyncio.run(run())
