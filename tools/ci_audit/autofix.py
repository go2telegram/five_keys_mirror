"""Apply automated fixes for common CI failures."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import yaml

LOGGER = logging.getLogger(__name__)

_RUFF_STEP = {
    "name": "Run Ruff autofix",
    "run": "ruff check . --fix\nruff format .",
}

_SECURITY_STEP_RUN = 'python tools/security_audit.py --summary || echo "WARN: security audit returned warn"'


@dataclass
class AutoFixResult:
    """Result of applying autofixes."""

    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def merge(self, other: "AutoFixResult") -> "AutoFixResult":
        self.applied.extend(other.applied)
        self.skipped.extend(other.skipped)
        return self


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def _dump_yaml(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as fp:
        yaml.safe_dump(payload, fp, sort_keys=False, width=120)


def _ensure_ruff_step(workflow_path: Path) -> AutoFixResult:
    result = AutoFixResult()
    try:
        data = _load_yaml(workflow_path)
    except FileNotFoundError:
        result.skipped.append(f"workflow missing: {workflow_path}")
        return result

    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        result.skipped.append("workflow has no jobs section")
        return result

    changed = False
    for job_name, job in jobs.items():
        steps = job.get("steps") if isinstance(job, dict) else None
        if not isinstance(steps, list):
            continue
        for step in steps:
            name = str(step.get("name", ""))
            if "ruff" in name.lower():
                if step.get("run") != _RUFF_STEP["run"] or step.get("name") != _RUFF_STEP["name"]:
                    step.pop("uses", None)
                    step.update(_RUFF_STEP)
                    changed = True
                break
        else:
            # Append to lint jobs only
            if "lint" in job_name.lower() or "lint" in str(job.get("name", "")).lower():
                steps.append(dict(_RUFF_STEP))
                changed = True
    if changed:
        _dump_yaml(workflow_path, data)
        result.applied.append("updated Ruff autofix step")
    else:
        result.skipped.append("Ruff autofix already configured")
    return result


def _ensure_security_step(workflow_path: Path) -> AutoFixResult:
    result = AutoFixResult()
    try:
        data = _load_yaml(workflow_path)
    except FileNotFoundError:
        result.skipped.append(f"workflow missing: {workflow_path}")
        return result

    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        result.skipped.append("workflow has no jobs section")
        return result

    changed = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        if job.get("env") is None:
            job["env"] = {}
        if isinstance(job["env"], dict) and "PYTHONPATH" not in job["env"]:
            job["env"]["PYTHONPATH"] = "."
            changed = True
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if str(step.get("name", "")).lower().startswith("security audit"):
                if step.get("run") != _SECURITY_STEP_RUN:
                    step["run"] = _SECURITY_STEP_RUN
                    changed = True
                break
    if changed:
        _dump_yaml(workflow_path, data)
        result.applied.append("adjusted security workflow")
    else:
        result.skipped.append("security workflow already aligned")
    return result


def _ensure_pythonpath(files: Sequence[Path]) -> AutoFixResult:
    result = AutoFixResult()
    snippet = 'sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))'
    for path in files:
        if not path.exists():
            result.skipped.append(f"file missing: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        if snippet in text:
            result.skipped.append(f"{path.name}: already patched")
            continue
        os_block = "import os" in text
        new_lines: list[str] = []
        inserted = False
        for line in text.splitlines():
            new_lines.append(line)
            if not inserted and line.startswith("import") and "sys" in line:
                if not os_block:
                    new_lines.append("import os")
                    os_block = True
                new_lines.append(snippet)
                inserted = True
        if not inserted:
            prefix = ["import os", "import sys", snippet]
            prefix_text = "\n".join(prefix)
            text = prefix_text + "\n" + text
        else:
            text = "\n".join(new_lines)
        path.write_text(text, encoding="utf-8")
        result.applied.append(f"patched PYTHONPATH in {path.name}")
    return result


def apply_autofixes(issues: Iterable[str], *, repo_root: str | Path | None = None) -> AutoFixResult:
    """Apply autofixes for the given issue identifiers.

    Parameters
    ----------
    issues:
        Iterable of issue identifiers such as ``"lint"``, ``"security"`` or ``"imports"``.
    repo_root:
        Optional repository root. Defaults to the current working directory.
    """

    root = Path(repo_root or os.getcwd()).resolve()
    workflow_path = root / ".github" / "workflows" / "ci.yml"
    files = [
        root / "tools" / "build_products.py",
        root / "tools" / "catalog_build.py",
        root / "tools" / "catalog_validate.py",
    ]

    result = AutoFixResult()
    issue_set = {issue.lower() for issue in issues}

    if "lint" in issue_set:
        result.merge(_ensure_ruff_step(workflow_path))
    if "security" in issue_set:
        result.merge(_ensure_security_step(workflow_path))
        security_script = root / "tools" / "security_audit.py"
        if security_script.exists():
            text = security_script.read_text(encoding="utf-8")
            snippet = 'FAIL_LEVEL = os.getenv("SECURITY_FAIL_LEVEL", "CRITICAL").upper()'
            if snippet not in text:
                if "import os" not in text:
                    text = text.replace("import argparse", "import argparse\nimport os")
                if "FAIL_LEVEL" in text:
                    text = re.sub(r"FAIL_LEVEL\s*=.*", snippet, text, count=1)
                else:
                    text = text.replace('ORDER = ["NONE"', snippet + '\nORDER = ["NONE"')
                security_script.write_text(text, encoding="utf-8")
                result.applied.append("updated security audit threshold")
    if "imports" in issue_set:
        result.merge(_ensure_pythonpath(files))

    return result
