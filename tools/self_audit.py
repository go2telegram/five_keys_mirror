#!/usr/bin/env python3
"""Unified self-audit entry point for local and CI usage."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit_sections import (  # noqa: E402
    AuditContext,
    SectionResult,
    check_calculators,
    check_catalog,
    check_linters,
    check_load_smoke,
    check_media_urls,
    check_migrations,
    check_quizzes,
    check_recommendations,
    check_security,
    check_tests_quality,
)

DEFAULT_REPORT = ROOT / "build" / "reports" / "self_audit.md"
JSON_REPORT = "self_audit.json"
TIMINGS_REPORT = "timings.json"


def _check_git_dirty(context: AuditContext) -> SectionResult:
    try:
        result = context.run(["git", "status", "--porcelain"], check=False)
    except Exception as exc:  # pragma: no cover - defensive
        return SectionResult(
            name="git_dirty",
            status="error",
            summary="Не удалось проверить состояние git.",
            details=[str(exc)],
        )

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines:
        return SectionResult(
            name="git_dirty",
            status="warn",
            summary="Рабочее дерево содержит несохранённые изменения.",
            details=lines,
        )
    return SectionResult(
        name="git_dirty",
        status="ok",
        summary="Рабочее дерево чистое.",
    )


_SECTION_HANDLERS: Dict[str, Callable[[AuditContext], SectionResult]] = {
    "git_dirty": _check_git_dirty,
    "migrations": check_migrations.run,
    "catalog": check_catalog.run,
    "media": check_media_urls.run,
    "quizzes": check_quizzes.run,
    "calculators": check_calculators.run,
    "recommendations": check_recommendations.run,
    "tests": check_tests_quality.run,
    "linters": check_linters.run,
    "security": check_security.run,
    "load_smoke": check_load_smoke.run,
}

_GROUPS = [
    ("Git", ["git_dirty"]),
    ("Миграции", ["migrations"]),
    ("Каталог", ["catalog"]),
    ("Медиа", ["media"]),
    ("Квизы/Калькуляторы", ["quizzes", "calculators"]),
    ("Рекомендации", ["recommendations"]),
    ("Тесты/линтеры/безопасность", ["tests", "linters", "security"]),
    ("Нагрузка (smoke)", ["load_smoke"]),
]

_FAST_SKIPS = {"linters", "load_smoke"}
_CRITICAL_FOR_CI = {"migrations", "catalog", "tests", "pytest"}

_STATUS_EMOJI = {
    "ok": "✅",
    "warn": "⚠️",
    "error": "❌",
    "skip": "⏭️",
}


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="Пропустить линтеры и нагрузочный смоук")
    parser.add_argument("--ci", action="store_true", help="CI-режим: выход с ошибкой при критических проблемах")
    parser.add_argument(
        "--ci-merge",
        action="store_true",
        help="CI merge-guard режим: завершаться с ошибкой при критических проблемах",
    )
    parser.add_argument("--no-net", action="store_true", help="Пропустить сетевые проверки")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="Путь к Markdown-отчёту")
    return parser.parse_args(argv)


def _git_info() -> dict:
    info: dict[str, str | None] = {"commit": None, "branch": None}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=True,
        )
        info["commit"] = result.stdout.strip()
    except Exception:
        info["commit"] = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=True,
        )
        info["branch"] = result.stdout.strip()
    except Exception:
        info["branch"] = None
    return info


def _render_markdown(metadata: dict, results: Dict[str, SectionResult]) -> str:
    lines: list[str] = []
    title = "Self-audit report"
    if metadata.get("commit"):
        title += f" ({metadata['commit']})"
    generated = metadata.get("generated_at")
    lines.append(f"# {title}")
    if generated:
        lines.append(f"_Создано: {generated}_")
    if metadata.get("branch"):
        lines.append(f"_Ветка: {metadata['branch']}_")
    lines.append("")

    for heading, names in _GROUPS:
        lines.append(f"## {heading}")
        group_lines = []
        for name in names:
            result = results.get(name)
            if result is None:
                continue
            emoji = _STATUS_EMOJI.get(result.status, "•")
            group_lines.append(f"- {emoji} {result.summary}")
        if group_lines:
            lines.extend(group_lines)
        else:
            lines.append("- (нет данных)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, socket.gaierror)):
        return True
    if isinstance(exc, OSError) and exc.errno in {
        errno.ECONNREFUSED,
        errno.EHOSTUNREACH,
        errno.ECONNRESET,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }:
        return True
    module = type(exc).__module__
    if module.startswith("aiohttp") or module.startswith("urllib3"):
        return True
    name = type(exc).__name__.lower()
    return "http" in module or "network" in name or "timeout" in name


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)

    reports_path = (args.out if isinstance(args.out, Path) else Path(args.out)).resolve()
    reports_dir = reports_path.parent
    reports_dir.mkdir(parents=True, exist_ok=True)

    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = f"{ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(ROOT)

    context = AuditContext(
        root=ROOT,
        reports_dir=reports_dir,
        fast=args.fast,
        ci=args.ci or args.ci_merge,
        no_net=args.no_net or os.getenv("NO_NET") == "1",
        env={"PYTHONPATH": pythonpath},
    )

    if context.no_net:
        print("WARN: Self-audit running in no-network mode; external checks downgraded.", file=sys.stderr)

    results: Dict[str, SectionResult] = {}
    timings: Dict[str, float] = {}

    for name, handler in _SECTION_HANDLERS.items():
        if args.fast and name in _FAST_SKIPS:
            results[name] = SectionResult(name=name, status="skip", summary="Пропущено в режиме --fast.")
            continue
        start = time.perf_counter()
        try:
            result = handler(context)
        except Exception as exc:  # pragma: no cover - defensive
            if context.no_net and _is_network_error(exc):
                result = SectionResult(
                    name=name,
                    status="skip",
                    summary=f"Секция {name} пропущена из-за --no-net (сетевые ошибки).",
                    details=[str(exc)],
                )
            else:
                result = SectionResult(
                    name=name,
                    status="error",
                    summary=f"Исключение в секции {name}.",
                    details=[str(exc)],
                )
        end = time.perf_counter()
        timings[name] = round(end - start, 3)
        results[name] = result

    metadata = _git_info()
    metadata["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata["fast"] = args.fast
    metadata["ci"] = args.ci
    metadata["ci_merge"] = args.ci_merge
    metadata["no_net"] = context.no_net

    markdown = _render_markdown(metadata, results)
    reports_path.write_text(markdown, encoding="utf-8")

    json_path = reports_dir / JSON_REPORT
    json_payload = {
        "metadata": metadata,
        "sections": {name: result.to_dict() for name, result in results.items()},
        "timings": timings,
    }
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    timings_path = reports_dir / TIMINGS_REPORT
    timings_path.write_text(json.dumps(timings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    critical_errors = [
        name for name, result in results.items() if result.status in {"error", "fail"} and name in _CRITICAL_FOR_CI
    ]
    status_counts: Dict[str, int] = {}
    for result in results.values():
        status_counts[result.status] = status_counts.get(result.status, 0) + 1

    aggregate = {
        "status_counts": status_counts,
        "critical_errors": critical_errors,
        "report": str(reports_path.relative_to(ROOT)),
        "json": str(json_path.relative_to(ROOT)),
    }

    print(f"Markdown report: {reports_path}")
    print(json.dumps(aggregate, ensure_ascii=False))

    if args.ci or args.ci_merge:
        return 1 if critical_errors else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
