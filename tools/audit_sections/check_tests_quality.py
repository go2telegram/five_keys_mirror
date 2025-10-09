"""Run pytest for self-audit."""

from __future__ import annotations

import os
import sys

from . import AuditContext, SectionResult, section


@section("tests")
def run(ctx: AuditContext) -> SectionResult:
    if os.getenv("SELF_AUDIT_SKIP_TESTS") == "1":
        return SectionResult(
            name="tests",
            status="skip",
            summary="Pytest пропущен по SELF_AUDIT_SKIP_TESTS.",
        )

    command = [sys.executable, "-m", "pytest", "-q"]
    proc = ctx.run(command)

    if proc.returncode == 0:
        status = "ok"
        summary = "pytest: все тесты пройдены."
    else:
        status = "error"
        summary = "pytest завершился с ошибками."

    details = []
    if proc.stdout:
        details.append(proc.stdout.strip())
    if proc.stderr:
        details.append(proc.stderr.strip())

    data = {"returncode": proc.returncode}

    return SectionResult(
        name="tests",
        status=status,
        summary=summary,
        details=details,
        data=data,
    )
