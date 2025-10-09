#!/usr/bin/env python3
"""Run security tooling and summarise results.

The script executes pip-audit, safety, and bandit; gathers their findings;
produces a Markdown summary report, and returns 1 when High/Critical
vulnerabilities are detected.
"""
from __future__ import annotations

import json
import pathlib as pl
import subprocess as sp
import sys
from dataclasses import dataclass
from typing import List, Optional

ROOT = pl.Path(__file__).resolve().parents[1]
REPORTS = ROOT / "build" / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)
REPORT_PATH = REPORTS / "security_audit.md"

SEVERITY_ORDER = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}


@dataclass
class Finding:
    tool: str
    identifier: str
    package: Optional[str]
    installed: Optional[str]
    severity: str
    description: str

    def severity_level(self) -> int:
        return SEVERITY_ORDER.get(self.severity.lower(), 0)


def run(cmd: List[str]) -> sp.CompletedProcess[str]:
    result = sp.run(cmd, text=True, capture_output=True)
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        result.check_returncode()
    return result


def collect_pip_audit() -> List[Finding]:
    result = run(["pip-audit", "--format", "json"])
    findings: List[Finding] = []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return findings
    for entry in data:
        dependency = entry.get("dependency", {})
        package = dependency.get("name")
        installed = dependency.get("version")
        for vuln in entry.get("vulns", []):
            severity = (vuln.get("severity") or "unknown").lower()
            identifier = vuln.get("id") or vuln.get("aliases", ["unknown"])[0]
            description = vuln.get("description") or ""
            findings.append(
                Finding(
                    tool="pip-audit",
                    identifier=identifier,
                    package=package,
                    installed=installed,
                    severity=severity,
                    description=description.strip(),
                )
            )
    return findings


def collect_safety() -> List[Finding]:
    result = run(["safety", "check", "--json"])
    findings: List[Finding] = []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return findings
    if isinstance(data, dict):
        vulnerabilities = data.get("vulnerabilities") or []
    else:
        vulnerabilities = data
    for vuln in vulnerabilities:
        severity = (vuln.get("severity") or vuln.get("severity_level") or "unknown").lower()
        identifier = str(vuln.get("id") or vuln.get("vuln_id") or vuln.get("advisory") or "unknown")
        description = vuln.get("description") or vuln.get("advisory") or ""
        findings.append(
            Finding(
                tool="safety",
                identifier=identifier,
                package=vuln.get("package_name") or vuln.get("package") or "",
                installed=vuln.get("version") or vuln.get("affected_versions"),
                severity=severity,
                description=description.strip(),
            )
        )
    return findings


def collect_bandit() -> List[Finding]:
    target = ROOT / "app"
    if not target.exists():
        return []
    result = run(["bandit", "-r", str(target), "-f", "json"])
    findings: List[Finding] = []
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return findings
    for issue in data.get("results", []):
        severity = (issue.get("issue_severity") or "unknown").lower()
        identifier = issue.get("test_id") or "B???"
        description = issue.get("issue_text") or ""
        filename = issue.get("filename") or ""
        line = issue.get("line_number")
        location = f"{filename}:{line}" if line else filename
        findings.append(
            Finding(
                tool="bandit",
                identifier=identifier,
                package=location,
                installed=None,
                severity=severity,
                description=description.strip(),
            )
        )
    return findings


def build_report(findings: List[Finding]) -> str:
    if not findings:
        return "## Security audit\n\n_No issues detected by pip-audit, safety, or bandit._\n"
    lines = ["## Security audit", "", "| Tool | Identifier | Target | Severity | Description |", "| --- | --- | --- | --- | --- |"]
    for finding in findings:
        target = finding.package or ""
        if finding.installed:
            target = f"{target} ({finding.installed})" if target else finding.installed
        description = finding.description.replace("\n", " ")
        lines.append(
            f"| {finding.tool} | {finding.identifier} | {target} | {finding.severity.upper()} | {description} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    findings: List[Finding] = []
    findings.extend(collect_pip_audit())
    findings.extend(collect_safety())
    findings.extend(collect_bandit())

    report = build_report(findings)
    REPORT_PATH.write_text(report, encoding="utf-8")

    highest = 0
    for finding in findings:
        highest = max(highest, finding.severity_level())
    return 1 if highest >= SEVERITY_ORDER["high"] else 0


if __name__ == "__main__":
    sys.exit(main())
