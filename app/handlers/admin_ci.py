"""Admin command that shares the latest CI audit report."""

from __future__ import annotations

from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from .admin import _is_admin

router = Router(name="admin_ci")

ROOT = Path(__file__).resolve().parents[2]
REPORT_MD = ROOT / "build" / "reports" / "ci_audit.md"


@router.message(Command("ci_audit"))
async def handle_ci_audit(message: Message) -> None:
    """Send the last CI audit report to administrators."""

    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    if REPORT_MD.exists():
        payload = REPORT_MD.read_bytes()
        document = BufferedInputFile(payload, filename="ci_audit.md")
        await message.answer_document(document, caption="Последний отчёт ci-audit")
        return

    await message.answer("Запусти workflow ci-audit в Actions → будет отчёт через 1–2 мин")
