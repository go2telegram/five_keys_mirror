"""Admin command to trigger the self-audit pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .admin import _is_admin

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "build" / "reports"
SELF_AUDIT_SCRIPT = ROOT / "tools" / "self_audit.py"

router = Router(name="admin_audit")

_SECTION_TITLES = {
    "migrations": "Миграции",
    "catalog": "Каталог",
    "media": "Медиа",
    "quizzes": "Квизы",
    "calculators": "Калькуляторы",
    "recommendations": "Рекомендации",
    "tests": "Тесты",
    "linters": "Линтеры",
    "security": "Безопасность",
    "load_smoke": "Нагрузка",
}

_STATUS_EMOJI = {
    "ok": "✅",
    "warn": "⚠️",
    "error": "❌",
    "skip": "⏭️",
}

_CALLBACK_FULL = "admin:self_audit:full"


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Полный аудит (--ci)", callback_data=_CALLBACK_FULL)]
        ]
    )


def _shorten(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def _invoke_self_audit(
    *flags: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    env = os.environ.copy()
    if "--no-net" in flags:
        env["NO_NET"] = "1"
    cmd = [sys.executable, str(SELF_AUDIT_SCRIPT), *flags]

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)

    proc = await asyncio.to_thread(_run)
    json_path = REPORT_DIR / "self_audit.json"
    data: dict[str, Any] = {}
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return proc, data


def _format_summary(data: dict[str, Any], *, flags: Iterable[str], returncode: int) -> str:
    meta = data.get("metadata", {})
    sections = data.get("sections", {})
    header = "🧪 Self-audit " + " ".join(flags or ["--fast"])
    info_lines = [header]
    if meta:
        info_lines.append(
            "Коммит: {commit} | Ветка: {branch}".format(
                commit=meta.get("commit", "—"), branch=meta.get("branch", "—")
            )
        )
    for key in [
        "migrations",
        "catalog",
        "media",
        "quizzes",
        "calculators",
        "recommendations",
        "tests",
        "linters",
        "security",
        "load_smoke",
    ]:
        info = sections.get(key)
        if not info:
            continue
        emoji = _STATUS_EMOJI.get(info.get("status"), "•")
        title = _SECTION_TITLES.get(key, key)
        summary = _shorten(info.get("summary", ""))
        info_lines.append(f"{emoji} {title}: {summary}")
    if returncode != 0:
        info_lines.append(f"❗️ Завершено с кодом {returncode}")
    return "\n".join(info_lines)


async def _send_report(target: Message | CallbackQuery, *, flags: list[str]) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    if message is None:
        return

    await message.answer("⏳ Запускаю self-audit…")
    proc, data = await _invoke_self_audit(*flags)
    summary = _format_summary(data, flags=flags or ["--fast"], returncode=proc.returncode)
    await message.answer(summary, reply_markup=_keyboard())

    report_path = REPORT_DIR / "self_audit.md"
    if report_path.exists():
        payload = report_path.read_bytes()
        document = BufferedInputFile(payload, filename="self_audit.md")
        await message.answer_document(document, caption="Полный отчёт self-audit")
    else:
        await message.answer("⚠️ Отчёт не найден.")

    if proc.returncode != 0 and proc.stderr:
        await message.answer(f"stderr:\n{_shorten(proc.stderr, 3500)}")


@router.message(Command("self_audit"))
async def handle_self_audit(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    flags = ["--fast"]
    if os.getenv("NO_NET") == "1":
        flags.append("--no-net")
    await _send_report(message, flags=flags)


@router.callback_query(F.data == _CALLBACK_FULL)
async def handle_self_audit_full(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer()
        return
    flags = ["--ci"]
    if os.getenv("NO_NET") == "1":
        flags.append("--no-net")
    await callback.answer("Запуск полного self-audit", show_alert=False)
    await _send_report(callback, flags=flags)
