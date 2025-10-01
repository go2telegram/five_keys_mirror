#!/usr/bin/env python3
"""Verify that all PowerShell scripts contain ASCII-only text."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

failures: list[str] = []

for path in sorted(SCRIPTS.glob("*.ps1")):
    data = path.read_bytes()
    if any(b > 127 for b in data):
        failures.append(f"{path.relative_to(ROOT)} contains non-ASCII bytes")

if failures:
    for item in failures:
        print(f"::error ::{item}")
    print("PowerShell 5.1 requires ASCII-only scripts in scripts/*.ps1", file=sys.stderr)
    sys.exit(1)

print("ASCII check passed for scripts/*.ps1")
