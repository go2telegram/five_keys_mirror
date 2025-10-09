"""Media URL availability audit."""

from __future__ import annotations

import os
from pathlib import Path

from . import AuditContext, SectionResult, section


REPORT_NAME = "media_head_report.txt"
LEGACY_REPORT = Path("build/images_head_report.txt")


def _copy_legacy_report(root: Path, reports_dir: Path) -> Path | None:
    source = root / LEGACY_REPORT
    if not source.exists():
        return None
    target = reports_dir / REPORT_NAME
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@section("media")
def run(ctx: AuditContext) -> SectionResult:
    if ctx.no_net or os.getenv("NO_NET") == "1":
        return SectionResult(
            name="media",
            status="skip",
            summary="Проверка медиа пропущена (NO_NET=1).",
        )

    try:
        from tools import head_check
    except Exception as exc:  # pragma: no cover - import issues
        return SectionResult(
            name="media",
            status="error",
            summary="Не удалось импортировать head_check.",
            details=[str(exc)],
        )

    exit_code = head_check.main()
    report_path = _copy_legacy_report(ctx.root, ctx.reports_dir)
    lines = []
    errors = 0
    warnings = 0
    if report_path and report_path.exists():
        for line in report_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            status_code = line.split("\t", 1)[0]
            if status_code.upper() in {"ERR", "404", "500", "502"}:
                errors += 1
            elif status_code not in {"200", "204", "301", "302"}:
                warnings += 1
            lines.append(line)

    if exit_code != 0:
        status = "warn" if errors == 0 else "error"
        detail = f"head_check завершился с кодом {exit_code}."
    else:
        status = "ok" if errors == 0 else "warn"
        detail = None

    details: list[str] = []
    if detail:
        details.append(detail)
    if errors:
        details.append(f"Ошибок: {errors}.")
    if warnings:
        details.append(f"Предупреждений: {warnings}.")

    summary = f"HEAD-проверка: ok (ошибок={errors}, предупреждений={warnings})."
    if status == "warn" and errors:
        summary = f"HEAD-проверка завершена с ошибками ({errors})."

    data = {
        "errors": errors,
        "warnings": warnings,
        "report": str(report_path) if report_path else None,
    }

    return SectionResult(
        name="media",
        status=status,
        summary=summary,
        details=details,
        data=data,
    )
