"""Marketing creative generator backed by LLM templates."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from app.utils_openai import ai_generate


class CreativeGenerationError(RuntimeError):
    """Raised when LLM answer cannot be parsed or generation fails."""


@dataclass
class Creative:
    """Single creative variant."""

    title: str
    text: str
    cta: str

    def to_markdown(self) -> str:
        body = self.text.strip()
        cta = self.cta.strip()
        md_parts = []
        if self.title:
            md_parts.append(f"# {self.title.strip()}")
        if body:
            md_parts.append(body)
        if cta:
            md_parts.append(f"**CTA:** {cta}")
        return "\n\n".join(md_parts).strip() + "\n"

    def to_plain(self) -> str:
        parts = []
        if self.title:
            parts.append(self.title.strip())
        body = self.text.strip()
        if body:
            parts.append(body)
        cta = self.cta.strip()
        if cta:
            parts.append(f"CTA: {cta}")
        return "\n\n".join(parts).strip() + "\n"


@dataclass
class CreativeBatch:
    """Result of generation: creatives plus saved file paths."""

    format_code: str
    format_label: str
    creatives: List[Creative]
    markdown_files: List[Path]
    text_files: List[Path]
    warnings: List[str]


FORMAT_GUIDES: Dict[str, Dict[str, Iterable[str] | str]] = {
    "telegram": {
        "label": "Telegram пост",
        "aliases": {"tg", "telegram", "телеграм"},
        "prompt": (
            "Короткий пост с цепляющим вступлением,\n"
            "буллеты с выгодами/фактами (2-4 пункта) и финальный вывод."),
    },
    "instagram": {
        "label": "Instagram пост",
        "aliases": {"insta", "instagram", "ig", "инстаграм"},
        "prompt": (
            "Структура: цепляющий заголовок,\n"
            "эмоциональный сторителлинг в 2-3 абзаца,\n"
            "буллеты с пользой и финальный призыв."),
    },
    "reels": {
        "label": "Reels сценарий",
        "aliases": {"reels", "reel", "shorts", "риелс", "риелсы"},
        "prompt": (
            "Дай структуру для короткого вертикального видео:"
            "\n- Хук (1-2 короткие фразы)"
            "\n- Основные тезисы по шагам"
            "\n- Финальный акцент и CTA."),
    },
}

DEFAULT_FORMAT = "telegram"
SYSTEM_PROMPT = (
    "Ты — опытный маркетолог и копирайтер. "
    "Пиши на современном русском языке, адаптируйся под указанную аудиторию. "
    "Всегда соблюдай ограничения по длине и структуре." 
)
MIN_VARIANTS = 3
MAX_VARIANTS = 5
MAX_TOTAL_LENGTH = 2200


def _normalize_format(name: str | None) -> str:
    if not name:
        return DEFAULT_FORMAT
    name = name.strip().lower()
    for code, data in FORMAT_GUIDES.items():
        if name == code or name in data.get("aliases", {}):
            return code
    return DEFAULT_FORMAT


def _clean_json_payload(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, count=1, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    match = re.search(r"\{.*\}\s*$", raw, re.DOTALL)
    if match:
        return match.group(0)
    return raw


def _parse_creatives(raw: str) -> List[Creative]:
    payload = _clean_json_payload(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CreativeGenerationError(f"Не удалось разобрать ответ модели: {exc}") from exc

    items = data
    if isinstance(data, dict):
        items = data.get("creatives") or data.get("items") or data.get("variants")
    if not isinstance(items, list):
        raise CreativeGenerationError("Ответ модели не содержит списка креативов.")

    creatives: List[Creative] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("headline") or "").strip()
        body = str(item.get("text") or item.get("body") or item.get("content") or "").strip()
        cta = str(item.get("cta") or item.get("call_to_action") or "").strip()
        if not body:
            continue
        creatives.append(Creative(title=title, text=body, cta=cta))

    if not creatives:
        raise CreativeGenerationError("Не удалось получить креативы из ответа модели.")

    return creatives


def _apply_length_limit(creative: Creative) -> tuple[Creative, str | None]:
    warning: str | None = None
    body = creative.text.strip()
    cta = creative.cta.strip()
    total_len = len(body) + (len(cta) + 2 if cta else 0)
    if total_len <= MAX_TOTAL_LENGTH:
        return creative, None

    available = MAX_TOTAL_LENGTH - (len(cta) + 2 if cta else 0)
    if available < 0:
        available = MAX_TOTAL_LENGTH
        cta = cta[:MAX_TOTAL_LENGTH]
    if len(body) > available:
        warning = "Текст был сокращён, чтобы уложиться в лимит 2200 символов."
        body = body[: max(available - 1, 0)].rstrip()
        if body and body[-1] not in {".", "!", "?", "…"}:
            body = body.rstrip(" ,;") + "…"
    creative = Creative(title=creative.title, text=body, cta=cta)
    return creative, warning


async def generate_creatives(
    *,
    theme: str,
    audience: str | None = None,
    format_name: str | None = None,
    tone: str | None = None,
    variants: int | None = None,
) -> CreativeBatch:
    if not theme or not theme.strip():
        raise CreativeGenerationError("Не указана тема для генерации.")

    format_code = _normalize_format(format_name)
    guide = FORMAT_GUIDES[format_code]
    format_label = str(guide["label"])

    count = variants or MIN_VARIANTS
    count = max(MIN_VARIANTS, min(MAX_VARIANTS, count))

    audience_line = audience.strip() if audience else ""
    tone_line = tone.strip() if tone else ""

    prompt_lines = [
        f"Тема: {theme.strip()}.",
        f"Количество вариантов: {count}.",
        f"Формат: {format_label}.",
        guide["prompt"],
        "Каждый креатив должен включать: заголовок (title), основной текст (text), CTA (cta).",
        "CTA делай конкретным действием. Весь текст (text + CTA) ≤ 2200 символов.",
        "Пиши на русском языке.",
        "Не повторяйся — каждый вариант должен раскрывать тему с новой стороны.",
        "Верни JSON формата {\"creatives\": [{\"title\": ..., \"text\": ..., \"cta\": ...}, ...]} без дополнительных пояснений.",
    ]
    if audience_line:
        prompt_lines.insert(1, f"ЦА: {audience_line}.")
    if tone_line:
        prompt_lines.append(f"Тональность: {tone_line}.")

    prompt = "\n".join(prompt_lines)

    raw = await ai_generate(prompt, sys=SYSTEM_PROMPT)
    if not raw:
        raise CreativeGenerationError("Модель вернула пустой ответ.")

    creatives = _parse_creatives(raw)
    if len(creatives) < MIN_VARIANTS:
        raise CreativeGenerationError(
            f"Модель вернула недостаточно вариантов: {len(creatives)} из {MIN_VARIANTS} минимум.")

    trimmed_creatives: List[Creative] = []
    warnings: List[str] = []
    for creative in creatives[:count]:
        adjusted, warning = _apply_length_limit(creative)
        trimmed_creatives.append(adjusted)
        if warning and warning not in warnings:
            warnings.append(warning)

    saved_md: List[Path] = []
    saved_txt: List[Path] = []

    now = datetime.now()
    base_dir = Path("media") / "creatives" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%H%M%S")
    for idx, creative in enumerate(trimmed_creatives, start=1):
        stem = f"{timestamp}_{format_code}_{idx:02d}"
        md_path = base_dir / f"{stem}.md"
        txt_path = base_dir / f"{stem}.txt"
        md_path.write_text(creative.to_markdown(), encoding="utf-8")
        txt_path.write_text(creative.to_plain(), encoding="utf-8")
        saved_md.append(md_path)
        saved_txt.append(txt_path)

    return CreativeBatch(
        format_code=format_code,
        format_label=format_label,
        creatives=trimmed_creatives,
        markdown_files=saved_md,
        text_files=saved_txt,
        warnings=warnings,
    )
