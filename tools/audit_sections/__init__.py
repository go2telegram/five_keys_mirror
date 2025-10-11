"""Shared helpers for self-audit sections."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

Status = str


@dataclass(slots=True)
class AuditContext:
    """Runtime context shared between audit checks."""

    root: Path
    reports_dir: Path
    fast: bool = False
    ci: bool = False
    no_net: bool = False
    env: Dict[str, str] = field(default_factory=dict)

    def child(self, **overrides: Any) -> "AuditContext":
        data = {
            "root": self.root,
            "reports_dir": self.reports_dir,
            "fast": self.fast,
            "ci": self.ci,
            "no_net": self.no_net,
            "env": dict(self.env),
        }
        data.update(overrides)
        return AuditContext(**data)

    def run(
        self,
        command: Iterable[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(self.env)
        if self.no_net:
            env.setdefault("NO_NET", "1")
        text_command = list(command)
        return subprocess.run(
            text_command,
            cwd=str(cwd or self.root),
            env=env,
            text=True,
            capture_output=True,
            check=check,
        )


@dataclass(slots=True)
class SectionResult:
    name: str
    status: Status
    summary: str
    details: list[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "details": list(self.details),
            "data": self.data,
        }


def section(
    name: str,
    func: Callable[[AuditContext], SectionResult] | None = None,
) -> Callable[[AuditContext], SectionResult]:
    """Decorator to attach a canonical name to a section function."""

    def decorator(inner: Callable[[AuditContext], SectionResult]) -> Callable[[AuditContext], SectionResult]:
        def wrapper(ctx: AuditContext) -> SectionResult:
            result = inner(ctx)
            if result.name != name:
                result = SectionResult(
                    name=name,
                    status=result.status,
                    summary=result.summary,
                    details=result.details,
                    data=result.data,
                )
            return result

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


__all__ = ["AuditContext", "SectionResult", "section"]
