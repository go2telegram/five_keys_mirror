"""Catalog build/validation audit section."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import AuditContext, SectionResult, section


SUMMARY_SOURCE = Path("app/catalog/mapping/build_summary.json")
REPORT_COPY = "catalog_summary.json"


def _load_summary(root: Path) -> dict:
    path = root / SUMMARY_SOURCE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@section("catalog")
def run(ctx: AuditContext) -> SectionResult:
    summary = {}
    details: list[str] = []
    status = "ok"

    if os.getenv("SELF_AUDIT_SKIP_CATALOG") == "1":
        status = "skip"
        summary_text = "Каталог пропущен по SELF_AUDIT_SKIP_CATALOG."
    else:
        builder = [
            sys.executable,
            str(ctx.root / "tools" / "build_products.py"),
            "build",
        ]
        proc_build = ctx.run(builder)
        if proc_build.returncode != 0:
            status = "error"
            details.append(proc_build.stderr.strip() or proc_build.stdout.strip())

        validator = [
            sys.executable,
            str(ctx.root / "tools" / "build_products.py"),
            "validate",
        ]
        proc_validate = ctx.run(validator)
        if proc_validate.returncode != 0:
            status = "error"
            details.append(proc_validate.stderr.strip() or proc_validate.stdout.strip())

        summary = _load_summary(ctx.root)
        built = int(summary.get("built", summary.get("count", 0)) or 0)
        unmatched = int(summary.get("unmatched", 0) or 0)
        expect = summary.get("expected", 0)
        if built < 1:
            status = "error"
            details.append("Каталог не содержит продуктов (built < 1).")
        summary_text = f"Каталог построен: {built} продуктов, unmatched={unmatched}."
        if expect:
            summary_text += f" Ожидалось: {expect}."

    reports_path = ctx.reports_dir / REPORT_COPY
    if summary:
        reports_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        reports_path.write_text("{}\n", encoding="utf-8")

    return SectionResult(
        name="catalog",
        status=status,
        summary=summary_text,
        details=details,
        data=summary,
    )
