"""Database migrations audit step."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

from . import AuditContext, SectionResult, section

ALEMBIC_TMP_PREFIX = "_alembic_tmp_"


def _collect_latest_revision(root: Path) -> str | None:
    versions_dir = root / "alembic" / "versions"
    if not versions_dir.exists():
        return None
    candidates: list[Path] = sorted(versions_dir.glob("*.py"))
    if not candidates:
        return None
    latest = candidates[-1].stem
    return latest


def _cleanup_tmp_versions(root: Path) -> None:
    versions_dir = root / "alembic" / "versions"
    if not versions_dir.exists():
        return
    for path in versions_dir.glob(f"{ALEMBIC_TMP_PREFIX}*"):
        try:
            path.unlink()
        except OSError:
            continue


def _run_alembic(ctx: AuditContext, args: Iterable[str]) -> tuple[bool, str]:
    command = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(ctx.root / "alembic.ini"),
    ]
    command.extend(args)
    proc = ctx.run(command)
    if proc.returncode == 0:
        return True, proc.stdout.strip()
    return False, (proc.stderr or proc.stdout or "alembic command failed").strip()


@section("migrations")
def run(ctx: AuditContext) -> SectionResult:
    if os.getenv("SELF_AUDIT_SKIP_MIGRATIONS") == "1":
        return SectionResult(
            name="migrations",
            status="skip",
            summary="Миграции пропущены по SELF_AUDIT_SKIP_MIGRATIONS.",
        )

    config_path = ctx.root / "alembic.ini"
    if not config_path.exists():
        return SectionResult(
            name="migrations",
            status="skip",
            summary="alembic.ini не найден, проверка миграций пропущена.",
        )

    _cleanup_tmp_versions(ctx.root)

    ok_sql, sql_output = _run_alembic(ctx, ["upgrade", "head", "--sql"])
    details: list[str] = []
    status = "ok" if ok_sql else "warn"
    if not ok_sql:
        details.append(f"alembic upgrade --sql failed: {sql_output}")

    ok_apply = False
    if os.getenv("SELF_AUDIT_OFFLINE_ONLY") != "1":
        apply_args = ["upgrade", "head"]
        ok_apply, apply_output = _run_alembic(ctx, apply_args)
        if not ok_apply:
            status = "error"
            details.append(f"alembic upgrade head failed: {apply_output}")
    else:
        details.append("Полное применение миграций пропущено (SELF_AUDIT_OFFLINE_ONLY=1).")
        ok_apply = True

    revision = _collect_latest_revision(ctx.root)
    summary = "Миграции применены успешно." if status == "ok" else "Проблемы с миграциями."
    if revision:
        summary = f"{summary} Последняя ревизия: {revision}."

    data = {
        "revision": revision,
        "sql_check": ok_sql,
        "applied": ok_apply,
    }

    return SectionResult(
        name="migrations",
        status=status,
        summary=summary,
        details=details,
        data=data,
    )
