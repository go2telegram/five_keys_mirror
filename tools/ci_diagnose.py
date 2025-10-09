"""CI failure diagnostics utility.

This script gathers information about recent CI runs and writes
``build/reports/ci_diagnostics.md`` and ``.json`` summaries. It is
intended to always succeed so that diagnostics are produced even when
some checks fail.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List


def run(cmd: str) -> Dict[str, Any]:
    """Execute a shell command and capture the important bits."""

    t0 = time.time()
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {"cmd": cmd, "error": str(exc)}

    duration = round(time.time() - t0, 1)
    return {
        "cmd": cmd,
        "code": completed.returncode,
        "stdout": completed.stdout[-500:],
        "stderr": completed.stderr[-500:],
        "t": duration,
    }


def main(argv: List[str] | None = None) -> int:
    del argv  # unused

    reports_dir = pathlib.Path("build/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    checks = [
        "python tools/self_audit.py --fast --no-net --out build/reports/self_audit_ci.md",
        "pytest -q --maxfail=1 --disable-warnings",
        "python -m compileall -q app tools || true",
    ]

    results: List[Dict[str, Any]] = [run(cmd) for cmd in checks]

    payload = {"env": dict(os.environ), "results": results}
    (reports_dir / "ci_diagnostics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    md_lines: List[str] = []
    for result in results:
        md_lines.append(f"### {result['cmd']}")
        code = result.get("code")
        if code is None:
            md_lines.append(f"Exit: {result.get('error', 'n/a')}")
        else:
            md_lines.append(f"Exit: {code}")
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        if stdout:
            md_lines.append(stdout.rstrip())
        if stderr:
            md_lines.append(stderr.rstrip())
        md_lines.append("---")

    (reports_dir / "ci_diagnostics.md").write_text(
        "\n".join(md_lines).rstrip() + "\n",
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
