import argparse
import json
import pathlib
import subprocess
import sys
from shutil import which
from typing import Any, Dict, Iterable

REPORTS_DIR = pathlib.Path("build/reports")


def has_gitleaks() -> bool:
    return which("gitleaks") is not None


def run_command(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def collect_reports() -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    results["pip_audit"] = run_command("pip-audit -r requirements.txt -f json").stdout or "[]"
    results["safety"] = run_command(
        "safety check --full-report -r requirements.txt --json"
    ).stdout or "[]"
    results["bandit"] = run_command("bandit -q -r app -f json").stdout or "{}"
    if has_gitleaks():
        # gitleaks exit code is non-zero when leaks are found; ignore to allow summary generation
        results["gitleaks"] = run_command(
            "gitleaks detect --no-git -f json --redact || true"
        ).stdout or "[]"
    else:
        results["gitleaks"] = "not-installed"
    return results


def write_reports(results: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "security_audit.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2)
    )
    gitleaks_output = results.get("gitleaks", "")
    if gitleaks_output == "not-installed":
        gitleaks_findings = "skipped (no binary)"
    else:
        gitleaks_findings = "issues" if '"leaks":' in gitleaks_output else "none"

    body = [
        "## Security audit",
        "",
        f"- pip-audit: {'issues' if results['pip_audit'] != '[]' else 'none'}",
        f"- safety: {'issues' if results['safety'] != '[]' else 'none'}",
        f"- bandit: {'issues' if results['bandit'] != '{}' else 'none'}",
        f"- gitleaks findings: {gitleaks_findings}",
    ]
    body.append(
        f"- gitleaks: {'scanned' if has_gitleaks() else 'skipped (no binary)'}"
    )
    summary = "\n".join(body) + "\n"
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


def has_high_findings(results: Dict[str, Any]) -> bool:
    pip_payload = _load_json(results["pip_audit"], [])
    for entry in pip_payload if isinstance(pip_payload, list) else []:
        for vuln in entry.get("vulns", []):
            if vuln.get("severity", "").upper() in {"HIGH", "CRITICAL"}:
                return True

    safety_payload = _load_json(results["safety"], [])
    for finding in _iter_safety_findings(safety_payload):
        if finding.get("severity", "").upper() in {"HIGH", "CRITICAL"}:
            return True

    bandit_payload = _load_json(results["bandit"], {})
    for finding in bandit_payload.get("results", []) if isinstance(bandit_payload, dict) else []:
        if finding.get("issue_severity", "").upper() in {"HIGH", "CRITICAL"}:
            return True

    return False


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

    if has_high_findings(reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
