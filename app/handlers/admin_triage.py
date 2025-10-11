from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from .admin import _is_admin

router = Router(name="admin_triage")

REPORT_PATH = Path(__file__).resolve().parents[2] / "build" / "reports" / "review_triage.md"


@router.message(Command("review_triage"))
async def handle_review_triage(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    if not REPORT_PATH.exists():
        await message.answer("Запусти triage из Actions: review-triage → Run workflow")
        return

    payload = REPORT_PATH.read_bytes()
    document = BufferedInputFile(payload, filename="review_triage.md")
    await message.answer_document(document, caption="Последний отчёт Codex triage")
