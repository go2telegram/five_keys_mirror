"""Basic secret scanning for self-audit."""

from __future__ import annotations

from pathlib import Path

from . import AuditContext, SectionResult, section


_SENSITIVE_HINTS = ("token", "secret", "api_key", "apikey", "password")
_TARGET_FILES = (".env", "config.py")


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    findings: list[str] = []
    for idx, line in enumerate(text.splitlines(), 1):
        lower = line.lower()
        if any(hint in lower for hint in _SENSITIVE_HINTS) and "=" in line:
            value = line.split("=", 1)[1].strip().strip('"\'')
            if value and len(value) > 8 and not value.startswith("${"):
                findings.append(f"{path.name}:{idx}")
    return findings


@section("security")
def run(ctx: AuditContext) -> SectionResult:
    findings: list[str] = []

    for target in _TARGET_FILES:
        path = ctx.root / target
        if path.exists():
            findings.extend(_scan_file(path))

    for env_file in ctx.root.glob("*.env"):
        if env_file.name == ".env":
            continue
        findings.extend(_scan_file(env_file))

    if findings:
        status = "warn"
        summary = f"Обнаружены потенциальные секреты: {len(findings)} записей."
    else:
        status = "ok"
        summary = "Секреты не найдены в проверенных файлах."

    return SectionResult(
        name="security",
        status=status,
        summary=summary,
        details=findings,
        data={"findings": findings},
    )
