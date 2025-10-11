"""Simple secret scanner for local files and git history."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
    re.compile(r"(?i)(api|secret|token)[^\n]{0,10}[:=]\s*[\"']?[A-Za-z0-9_-]{24,}"),
]
_GIT_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{36}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
]
_TARGET_FILES = [Path(".env"), Path("app/config.py"), Path("config.py")]


@dataclass(slots=True)
class Finding:
    location: str
    pattern: str
    line_preview: str

    def format(self) -> str:
        return f"{self.location}: {self.pattern} :: {self.line_preview}"


def _scan_file(path: Path) -> list[Finding]:
    if not path.exists():
        return []
    findings: list[Finding] = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return findings

    for idx, line in enumerate(content, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern in _PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        location=f"{path}:{idx}",
                        pattern=pattern.pattern,
                        line_preview=stripped[:160],
                    )
                )
                break
    return findings


def _chunks(seq: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for idx in range(0, len(seq), size):
        yield seq[idx : idx + size]


def _scan_git(patterns: Iterable[str]) -> list[Finding]:
    try:
        revs_raw = subprocess.run(
            ["git", "rev-list", "--all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        return []

    revs = [rev for rev in revs_raw if rev]
    if not revs:
        return []

    findings: list[Finding] = []
    for chunk in _chunks(revs, 64):
        for pattern in patterns:
            cmd = ["git", "grep", "-n", "--perl-regexp", "-e", pattern, *chunk]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    findings.append(
                        Finding(
                            location=f"git:{line.split(':', 1)[0]}",
                            pattern=pattern,
                            line_preview=line,
                        )
                    )
            elif proc.returncode not in (0, 1):
                raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
    return findings


def main() -> int:
    findings: list[Finding] = []
    for file_path in _TARGET_FILES:
        findings.extend(_scan_file(file_path))

    findings.extend(_scan_git(_GIT_PATTERNS))

    if findings:
        print("Potential secrets detected:")
        for finding in findings:
            print("  -", finding.format())
        return 1

    print("Secret audit passed: no secrets detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
