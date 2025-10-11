#!/usr/bin/env python3
"""Local development smoke checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Task:
    key: str
    label: str
    command: list[str]
    critical: bool = False
    skip_in_fast: bool = False


STATUS_ICONS = {
    "OK": "✅",
    "WARN": "⚠️",
    "FAIL": "❌",
    "SKIP": "⏭️",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_reports_dir(root: Path) -> Path:
    reports_dir = root / "build" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def short_note(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return ""


def run_task(task: Task, env: dict[str, str]) -> dict[str, Any]:
    start = time.perf_counter()
    proc = subprocess.run(task.command, capture_output=True, text=True, env=env)
    duration = time.perf_counter() - start
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    note = short_note(stdout, stderr)
    status = "OK" if proc.returncode == 0 else ("FAIL" if task.critical else "WARN")
    return {
        "task": task,
        "status": status,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "note": note,
        "duration": duration,
        "skipped": False,
    }


def skipped_task(task: Task, reason: str) -> dict[str, Any]:
    return {
        "task": task,
        "status": "SKIP",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "note": reason,
        "duration": 0.0,
        "skipped": True,
    }


def build_tasks(python: str) -> list[Task]:
    return [
        Task(
            key="build",
            label="Build product catalog",
            command=[python, "-m", "tools.build_products", "build"],
            critical=True,
        ),
        Task(
            key="validate",
            label="Validate product catalog",
            command=[python, "-m", "tools.build_products", "validate"],
            critical=True,
        ),
        Task(
            key="pytest",
            label="Pytest smoke",
            command=[
                python,
                "-m",
                "pytest",
                "-q",
                "-k",
                "smoke or start_home or calc_quiz_smoke",
            ],
            critical=True,
        ),
        Task(
            key="ruff",
            label="Ruff lint",
            command=[python, "-m", "ruff", "check", "."],
            critical=False,
        ),
        Task(
            key="bandit",
            label="Bandit security scan",
            command=[python, "-m", "bandit", "-q", "-r", "app", "-f", "json"],
            critical=False,
            skip_in_fast=True,
        ),
        Task(
            key="head_check",
            label="Head check media",
            command=[python, "tools/head_check.py"],
            critical=False,
            skip_in_fast=True,
        ),
    ]


def render_console(results: list[dict[str, Any]]) -> None:
    print("Dev check summary:")
    for result in results:
        task: Task = result["task"]
        status = result["status"]
        icon = STATUS_ICONS.get(status, status)
        duration = result["duration"]
        duration_str = f"{duration:.1f}s" if duration else "-"
        line = f"  {icon} {status:<4} {task.label} ({duration_str})"
        print(line)
        note = result.get("note")
        if note and status in {"WARN", "FAIL"}:
            for line in textwrap.wrap(note, width=74):
                print(f"      {line}")
        elif status == "SKIP" and note:
            print(f"      {note}")


def render_markdown(results: list[dict[str, Any]], report_path: Path) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Dev check summary",
        "",
        f"Generated at: {timestamp}",
        "",
        "| Step | Status | Duration | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        task: Task = result["task"]
        status = result["status"]
        icon = STATUS_ICONS.get(status, status)
        duration = result["duration"]
        duration_str = f"{duration:.2f}s" if duration else "-"
        note = result.get("note", "")
        note_safe = note.replace("|", "\\|")
        lines.append(f"| {task.label} | {icon} {status} | {duration_str} | {note_safe} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(results: list[dict[str, Any]], json_path: Path, exit_code: int) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "results": [
            {
                "key": res["task"].key,
                "label": res["task"].label,
                "status": res["status"],
                "returncode": res["returncode"],
                "duration": res["duration"],
                "critical": res["task"].critical,
                "skip_in_fast": res["task"].skip_in_fast,
                "skipped": res["skipped"],
                "note": res.get("note", ""),
                "stdout": res.get("stdout", ""),
                "stderr": res.get("stderr", ""),
            }
            for res in results
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local dev smoke checks")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip bandit and head_check steps",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write JSON report alongside the markdown summary",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    root = project_root()
    os.chdir(root)
    reports_dir = ensure_reports_dir(root)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")

    python = sys.executable
    tasks = build_tasks(python)
    results: list[dict[str, Any]] = []

    for task in tasks:
        if args.fast and task.skip_in_fast:
            results.append(skipped_task(task, "Skipped via --fast"))
            continue
        try:
            results.append(run_task(task, env))
        except KeyboardInterrupt:
            results.append(
                {
                    "task": task,
                    "status": "FAIL" if task.critical else "WARN",
                    "returncode": None,
                    "stdout": "",
                    "stderr": "Interrupted",
                    "note": "Interrupted",
                    "duration": 0.0,
                    "skipped": False,
                }
            )
            break

    render_console(results)
    report_path = reports_dir / "dev_check.md"
    render_markdown(results, report_path)

    exit_code = 1 if any(res["status"] == "FAIL" for res in results) else 0
    if args.json:
        json_path = reports_dir / "dev_check.json"
        write_json(results, json_path, exit_code)

    if exit_code != 0:
        print(f"dev_check completed with failures. See {report_path}", file=sys.stderr)
    elif any(res["status"] == "WARN" for res in results):
        print(f"dev_check completed with warnings. See {report_path}")
    else:
        print(f"dev_check completed successfully. Report: {report_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
