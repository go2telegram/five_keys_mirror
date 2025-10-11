import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
from typing import Any, Dict, Iterable

REPORTS_DIR = pathlib.Path("build/reports")

logger = logging.getLogger(__name__)

ORDER = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
FAIL_LEVEL = os.getenv("SECURITY_FAIL_LEVEL", "CRITICAL").upper()
if FAIL_LEVEL not in ORDER:
    FAIL_LEVEL = "CRITICAL"


def run_command(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def collect_reports() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    results["pip_audit"] = run_command("pip-audit -r requirements.txt -f json").stdout or "[]"
    results["safety"] = run_command("safety check --full-report -r requirements.txt --json").stdout or "[]"
    results["bandit"] = run_command("bandit -q -r app -f json").stdout or "{}"
    results["gitleaks"] = run_gitleaks_scan()
    return results


def run_gitleaks_scan() -> str:
    command = [
        "gitleaks",
        "detect",
        "--no-git",
        "-f",
        "json",
        "--redact",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"Skipping gitleaks (not installed): {exc}")
        return "not-installed"

    status = "OK" if completed.returncode == 0 else "WARN"
    print(f"Gitleaks done: {status}")
    return completed.stdout or "[]"


def write_reports(results: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "security_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    gitleaks_payload = results.get("gitleaks", "")
    gitleaks_has_leaks = '"leaks":' in gitleaks_payload if isinstance(gitleaks_payload, str) else bool(gitleaks_payload)
    gitleaks_summary = "skipped" if gitleaks_payload == "not-installed" else "issues" if gitleaks_has_leaks else "none"

    summary = (
        "## Security audit\n\n"
        f"- pip-audit: {'issues' if results['pip_audit'] != '[]' else 'none'}\n"
        f"- safety: {'issues' if results['safety'] != '[]' else 'none'}\n"
        f"- bandit: {'issues' if results['bandit'] != '{}' else 'none'}\n"
        f"- gitleaks: {gitleaks_summary}\n"
    )
    (REPORTS_DIR / "security_audit.md").write_text(summary)
    return summary


def _load_json(text: str, default: Any) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _iter_safety_findings(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        for finding in payload.get("vulnerabilities", []):
            if isinstance(finding, dict):
                yield finding
    elif isinstance(payload, list):
        for finding in payload:
            if isinstance(finding, dict):
                yield finding


def normalize_severity(value: Any) -> str:
    text = str(value).upper() if value is not None else ""
    return text if text in ORDER else "NONE"


def worse(left: str, right: str) -> str:
    return ORDER[max(ORDER.index(left), ORDER.index(right))]


def parse_pip_audit_max(text: str) -> str:
    payload = _load_json(text, [])
    maximum = "NONE"
    if isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            for vuln in entry.get("vulns", []) or []:
                if isinstance(vuln, dict):
                    maximum = worse(maximum, normalize_severity(vuln.get("severity")))
    return maximum


def parse_safety_max(text: str) -> str:
    payload = _load_json(text, [])
    maximum = "NONE"
    for finding in _iter_safety_findings(payload):
        maximum = worse(maximum, normalize_severity(finding.get("severity")))
    return maximum


def parse_bandit_max(text: str) -> str:
    payload = _load_json(text, {})
    maximum = "NONE"
    if isinstance(payload, dict):
        for finding in payload.get("results", []) or []:
            if isinstance(finding, dict):
                maximum = worse(maximum, normalize_severity(finding.get("issue_severity")))
    return maximum


def main() -> int:
    parser = argparse.ArgumentParser(description="Run security audits")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the Markdown summary to stdout",
    )
    args = parser.parse_args()

    reports = collect_reports()
    summary = write_reports(reports)

    if args.summary:
        print(summary, end="")

    pip_audit_max = parse_pip_audit_max(reports["pip_audit"])
    safety_max = parse_safety_max(reports["safety"])
    bandit_max = parse_bandit_max(reports["bandit"])

    max_all = "NONE"
    max_all = worse(max_all, pip_audit_max)
    max_all = worse(max_all, safety_max)
    max_all = worse(max_all, bandit_max)

    print(f"Security summary: max={max_all}")

    if ORDER.index(max_all) >= ORDER.index(FAIL_LEVEL):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
