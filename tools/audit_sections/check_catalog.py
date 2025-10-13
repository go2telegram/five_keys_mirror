"""Catalog build/validation audit section."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import AuditContext, SectionResult, section

SUMMARY_SOURCE = Path("app/catalog/mapping/build_summary.json")
REPORT_COPY = "catalog_summary.json"
LINKCHECK_LOG = Path("logs/catalog_linkcheck.log")


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
    linkcheck_data: dict[str, object] | None = None

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

        if not ctx.no_net and os.getenv("NO_NET") != "1":
            link_cmd = [
                sys.executable,
                str(ctx.root / "tools" / "catalog_linkcheck.py"),
                "--log",
                str(ctx.root / LINKCHECK_LOG),
            ]
            proc_links = ctx.run(link_cmd)
            stdout = proc_links.stdout.strip()
            summary_line = stdout.splitlines()[-1] if stdout else ""
            try:
                linkcheck_data = json.loads(summary_line) if summary_line else {}
            except json.JSONDecodeError:
                linkcheck_data = {}
            if proc_links.returncode == 1:
                if status == "ok":
                    status = "warn"
                broken = linkcheck_data.get("broken") if isinstance(linkcheck_data, dict) else None
                hint = (
                    f"catalog_linkcheck сообщил о проблемах (broken={broken})."
                    if broken is not None
                    else "catalog_linkcheck сообщил о проблемах."
                )
                details.append(hint)
            elif proc_links.returncode not in {0}:
                status = "error"
                detail = proc_links.stderr.strip() or proc_links.stdout.strip()
                if not detail:
                    detail = f"catalog_linkcheck завершился с кодом {proc_links.returncode}."
                details.append(detail)
        else:
            linkcheck_data = {"status": "skip", "reason": "NO_NET"}

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
        reports_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    else:
        reports_path.write_text("{}\n", encoding="utf-8")

    data = dict(summary)
    if linkcheck_data is not None:
        data["linkcheck"] = linkcheck_data

    return SectionResult(
        name="catalog",
        status=status,
        summary=summary_text,
        details=details,
        data=data,
    )
