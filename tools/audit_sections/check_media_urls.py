"""Media URL availability audit."""

from __future__ import annotations

import asyncio
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

    status = "ok"
    detail = None
    if exit_code != 0:
        status = "warn" if errors == 0 else "error"
        detail = f"head_check завершился с кодом {exit_code}."
    elif errors:
        status = "warn"

    partner_summary = None
    partner_details: list[str] = []
    partner_status = "ok"
    partner_data: dict[str, object] | None = None
    try:
        from app.services import partner_links
    except Exception as exc:  # pragma: no cover - optional dependency at runtime
        partner_status = "warn"
        partner_summary = f"Партнёрские ссылки: не удалось проверить ({exc})."
    else:
        try:
            results = asyncio.run(partner_links.check_partner_links())
        except Exception as exc:  # pragma: no cover - runtime issues
            partner_status = "warn"
            partner_summary = f"Партнёрские ссылки: проверка не удалась ({exc})."
        else:
            issues = partner_links.filter_partner_issues(results)
            total = len(results)
            if not total:
                partner_summary = "Партнёрские ссылки: не найдены в каталоге."
            elif issues:
                partner_status = "warn"
                partner_summary = (
                    f"Партнёрские ссылки: обнаружены проблемы ({len(issues)} из {total})."
                )
                for issue in issues[:10]:
                    parts: list[str] = []
                    if issue.error:
                        parts.append(issue.error)
                    if issue.status < 200 or issue.status >= 400:
                        parts.append(f"status={issue.status}")
                    if issue.utm_issues:
                        parts.extend(issue.utm_issues)
                    detail_line = "; ".join(parts) or "неизвестная ошибка"
                    partner_details.append(
                        f"{issue.link.product_id}: {detail_line} → {issue.link.url}"
                    )
                if len(issues) > 10:
                    partner_details.append(
                        f"… и ещё {len(issues) - 10} ссылок с проблемами"
                    )
            else:
                partner_summary = f"Партнёрские ссылки: ок ({total})."
            partner_data = {
                "checked": total,
                "issues": len(issues) if total else 0,
            }

    def _merge_status(current: str, other: str) -> str:
        priority = {"ok": 0, "skip": 0, "warn": 1, "error": 2}
        return current if priority.get(current, 0) >= priority.get(other, 0) else other

    status = _merge_status(status, partner_status)

    details: list[str] = []
    if detail:
        details.append(detail)
    if errors:
        details.append(f"Ошибок: {errors}.")
    if warnings:
        details.append(f"Предупреждений: {warnings}.")
    details.extend(partner_details)

    summary_parts = [
        f"HEAD-проверка: ok (ошибок={errors}, предупреждений={warnings})."
        if errors == 0
        else f"HEAD-проверка завершена с ошибками ({errors}).",
    ]
    if partner_summary:
        summary_parts.append(partner_summary)
    summary = " ".join(summary_parts)

    data = {
        "errors": errors,
        "warnings": warnings,
        "report": str(report_path) if report_path else None,
        "partner": partner_data,
    }

    return SectionResult(
        name="media",
        status=status,
        summary=summary,
        details=details,
        data=data,
    )
