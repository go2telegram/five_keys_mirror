"""Quiz YAML validation for self-audit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

import yaml

from . import AuditContext, SectionResult, section

QUIZ_DIR = Path("app/quiz/data")


@dataclass(slots=True)
class ValidationIssue:
    level: str
    message: str


def _iter_images(data: dict[str, Any]) -> Iterable[str]:
    cover = data.get("cover")
    if isinstance(cover, str):
        yield cover
    for question in data.get("questions", []) or []:
        if not isinstance(question, dict):
            continue
        image = question.get("image")
        if isinstance(image, str):
            yield image


def validate_quiz_payload(name: str, data: dict[str, Any], *, image_mode: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    questions = data.get("questions")
    if not isinstance(questions, list) or len(questions) < 5:
        issues.append(
            ValidationIssue(
                level="error",
                message=f"[{name}] Недостаточно вопросов (минимум 5).",
            )
        )

    result = data.get("result") or {}
    thresholds = result.get("thresholds") if isinstance(result, dict) else None
    if not isinstance(thresholds, list) or not thresholds:
        issues.append(
            ValidationIssue(
                level="error",
                message=f"[{name}] Раздел result.thresholds отсутствует или пуст.",
            )
        )

    if image_mode == "remote":
        for ref in _iter_images(data):
            if ref.startswith("http://") or ref.startswith("https://"):
                continue
            if ref.startswith("/"):
                issues.append(
                    ValidationIssue(
                        level="error",
                        message=f"[{name}] Абсолютный путь к изображению недопустим: {ref}",
                    )
                )

    return issues


@section("quizzes")
def run(ctx: AuditContext) -> SectionResult:
    quiz_dir = ctx.root / QUIZ_DIR
    if not quiz_dir.exists():
        return SectionResult(
            name="quizzes",
            status="skip",
            summary="Каталог с квизами не найден.",
        )

    image_mode = os.getenv("QUIZ_IMAGE_MODE", "remote").strip().lower() or "remote"

    errors = 0
    warnings = 0
    summaries: list[str] = []
    details: list[str] = []
    data: dict[str, Any] = {}

    for path in sorted(quiz_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            errors += 1
            details.append(f"[{path.name}] Некорректный формат (ожидался словарь).")
            continue
        issues = validate_quiz_payload(path.stem, payload, image_mode=image_mode)
        level = "ok"
        if any(item.level == "error" for item in issues):
            errors += 1
            level = "error"
        elif issues:
            warnings += 1
            level = "warn"
        question_count = len(payload.get("questions") or [])
        summaries.append(f"{path.stem}: {question_count} вопросов ({level}).")
        for issue in issues:
            details.append(issue.message)
        data[path.stem] = {
            "questions": question_count,
            "issues": [issue.__dict__ for issue in issues],
        }

    if errors:
        status = "error"
    elif warnings:
        status = "warn"
    else:
        status = "ok"

    summary_text = "Квизы проверены: " + ", ".join(summaries) if summaries else "Квизы не найдены."

    return SectionResult(
        name="quizzes",
        status=status,
        summary=summary_text,
        details=details,
        data=data,
    )


__all__ = ["ValidationIssue", "validate_quiz_payload", "run"]
