"""Run linters and static analyzers."""

from __future__ import annotations

import shutil

from . import AuditContext, SectionResult, section


_TOOLS = {
    "ruff": ["ruff", "check"],
    "mypy": ["mypy", "app"],
    "bandit": ["bandit", "-q", "-r", "app"],
}


@section("linters")
def run(ctx: AuditContext) -> SectionResult:
    statuses: list[str] = []
    details: list[str] = []
    errors = 0

    for name, command in _TOOLS.items():
        if shutil.which(command[0]) is None:
            statuses.append(f"{name}: не установлен")
            continue
        proc = ctx.run(command)
        if proc.returncode == 0:
            statuses.append(f"{name}: ok")
        else:
            errors += 1
            statuses.append(f"{name}: ошибки")
            if proc.stdout:
                details.append(proc.stdout.strip())
            if proc.stderr:
                details.append(proc.stderr.strip())

    if errors:
        status = "error"
    elif details:
        status = "warn"
    else:
        status = "ok"

    summary = "; ".join(statuses) if statuses else "Линтеры недоступны."

    return SectionResult(
        name="linters",
        status=status,
        summary=summary,
        details=details,
        data={"statuses": statuses},
    )
