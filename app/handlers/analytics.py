"""Admin analytics commands for funnel, cohorts and CTR reports."""

from __future__ import annotations

from pathlib import Path

from aiogram.filters import Command
from aiogram.types import Message
from aiogram import Router

from app.config import settings
from app.db.session import compat_session, session_scope
from app.services import analytics_reports

router = Router(name="analytics")


def _format_export_notice(path: Path | None) -> str:
    if path is None:
        return "\n⚠️ Не удалось сохранить CSV (проверь права на var/exports)."
    try:
        relative = path.relative_to(Path.cwd())
    except ValueError:
        relative = path
    return f"\n📁 CSV: {relative}"  # noqa: RUF001 - emoji preferred


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    admin_ids = {int(settings.ADMIN_ID)} if settings.ADMIN_ID else set()
    admin_ids.update(int(item) for item in settings.ADMIN_USER_IDS or [])
    return int(user_id) in admin_ids


@router.message(Command("funnel_report"))
async def funnel_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    async with compat_session(session_scope) as session:
        stats = await analytics_reports.gather_funnel(session)
    text = analytics_reports.format_funnel(stats)
    export_path = analytics_reports.export_funnel_csv(stats)
    await message.answer(text + _format_export_notice(export_path))


@router.message(Command("cohort_report"))
async def cohort_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    async with compat_session(session_scope) as session:
        rows = await analytics_reports.gather_cohorts(session)
    text = analytics_reports.format_cohorts(rows)
    export_path = analytics_reports.export_cohort_csv(rows)
    await message.answer(text + _format_export_notice(export_path))


@router.message(Command("ctr_report"))
async def ctr_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    async with compat_session(session_scope) as session:
        rows = await analytics_reports.gather_ctr(session)
    text = analytics_reports.format_ctr(rows)
    export_path = analytics_reports.export_ctr_csv(rows)
    await message.answer(text + _format_export_notice(export_path))


@router.message(Command("ab_report"))
async def ab_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    async with compat_session(session_scope) as session:
        rows = await analytics_reports.gather_onboarding_ab(session)
    text = analytics_reports.format_onboarding_ab(rows)
    await message.answer(text)


__all__ = ["router"]
