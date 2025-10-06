"""Admin command for generating marketing creatives."""
from __future__ import annotations

import shlex
from pathlib import Path
from typing import Dict

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from ai.creatives import CreativeGenerationError, generate_creatives
from app.config import settings

router = Router()


def _parse_kwargs(text: str | None) -> Dict[str, str]:
    if not text:
        return {}
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    result: Dict[str, str] = {}
    for token in parts[1:]:  # пропускаем саму команду
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key.lower()] = value
    return result


def _path_for_caption(path: Path) -> str:
    try:
        rel = path.relative_to(Path.cwd())
    except ValueError:
        rel = path
    return str(rel.as_posix())


@router.message(Command("generate_creative"))
async def generate_creative_command(message: Message) -> None:
    if not message.from_user or message.from_user.id != settings.ADMIN_ID:
        return

    args = _parse_kwargs(message.text or "")
    theme = args.get("theme") or args.get("тема")
    if not theme:
        await message.answer(
            "⚠️ Укажи тему: /generate_creative theme=детокс [audience=новички] [format=telegram] [tone=мягкий] [count=4]")
        return

    audience = args.get("audience") or args.get("target") or args.get("ца")
    format_name = args.get("format") or args.get("fmt")
    tone = args.get("tone") or args.get("voice")
    variants = None
    if "count" in args:
        try:
            variants = int(args["count"])
        except ValueError:
            variants = None

    try:
        batch = await generate_creatives(
            theme=theme,
            audience=audience,
            format_name=format_name,
            tone=tone,
            variants=variants,
        )
    except CreativeGenerationError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    header_lines = [
        "🎨 Креативы готовы!",
        f"Тема: <b>{theme}</b>",
        f"Формат: {batch.format_label}",
        f"Вариантов: {len(batch.creatives)}",
    ]
    if audience:
        header_lines.append(f"ЦА: {audience}")
    if tone:
        header_lines.append(f"Тональность: {tone}")
    if batch.warnings:
        header_lines.extend(f"⚠️ {w}" for w in batch.warnings)

    file_hints = [
        _path_for_caption(path)
        for path in batch.markdown_files + batch.text_files
    ]
    if file_hints:
        header_lines.append("Файлы:")
        header_lines.extend(f"• {hint}" for hint in file_hints)

    await message.answer("\n".join(header_lines))

    for idx, (creative, md_path) in enumerate(zip(batch.creatives, batch.markdown_files), start=1):
        caption = f"#{idx} — {creative.title}" if creative.title else f"#{idx}"
        await message.answer_document(
            BufferedInputFile(md_path.read_bytes(), filename=md_path.name),
            caption=caption,
        )
