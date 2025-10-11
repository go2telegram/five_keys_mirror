#!/usr/bin/env python3
"""Verify PowerShell scripts are ASCII-only and use CRLF with a single trailing newline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

failures: list[str] = []

for path in sorted(SCRIPTS_DIR.glob("*.ps1")):
    data = path.read_bytes()

    # ASCII discipline
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        failures.append(f"{path.relative_to(ROOT)} contains non-ASCII bytes")
        continue

    # Ensure all newlines are CRLF
    without_crlf = text.replace("\r\n", "")
    if "\r" in without_crlf or "\n" in without_crlf:
        failures.append(f"{path.relative_to(ROOT)} must use CRLF line endings only")
        continue

    # Require exactly one trailing CRLF
    if not text.endswith("\r\n"):
        failures.append(f"{path.relative_to(ROOT)} must end with CRLF newline")
        continue
    if text.endswith("\r\n\r\n"):
        failures.append(f"{path.relative_to(ROOT)} must have exactly one trailing blank line")
        continue

if failures:
    for item in failures:
        print(f"::error ::{item}")
    print("PowerShell scripts in scripts/ must be ASCII with CRLF and a single trailing newline", file=sys.stderr)
    sys.exit(1)

print("PowerShell scripts passed ASCII/CRLF checks")
