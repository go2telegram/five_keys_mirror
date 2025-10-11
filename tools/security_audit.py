import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import argparse
import json
import pathlib
import subprocess
from shutil import which
from typing import Any, Dict, Iterable

ALLOW_OFFLINE = os.getenv("ALLOW_OFFLINE_AUDIT", "").lower() in {"1", "true", "yes"}
OFFLINE_SENTINEL = "skipped (offline)"
REPORTS_DIR = pathlib.Path("build/reports")


def run_command(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def _capture_or_skip(name: str, command: str, *, empty: str) -> str:
    result = run_command(command)
    if result.returncode == 0:
        return result.stdout or empty
    if ALLOW_OFFLINE:
        print(
            f"⚠️ {name} failed (exit {result.returncode}); skipping check (offline mode)",
            file=sys.stderr,
        )
        return OFFLINE_SENTINEL
    return result.stdout or empty


def _offline_results() -> Dict[str, Any]:
    return {
        "pip_audit": OFFLINE_SENTINEL,
        "safety": OFFLINE_SENTINEL,
        "bandit": OFFLINE_SENTINEL,
        "gitleaks": OFFLINE_SENTINEL,
    }


def collect_reports() -> Dict[str, Any]:
    if ALLOW_OFFLINE and not which("gitleaks"):
        print("⚠️ gitleaks not found, skipping check (offline mode)")
        return _offline_results()

    results: Dict[str, Any] = {}
    results["pip_audit"] = _capture_or_skip(
        "pip-audit", "pip-audit -r requirements.txt -f json", empty="[]"
    )
    results["safety"] = _capture_or_skip(
        "safety", "safety check --full-report -r requirements.txt --json", empty="[]"
    )
    results["bandit"] = _capture_or_skip("bandit", "bandit -q -r app -f json", empty="{}")
    if which("gitleaks"):
        command = "gitleaks detect --no-git -f json --redact || true"
        payload = run_command(command)
        if payload.returncode == 0:
            results["gitleaks"] = payload.stdout or "[]"
        elif ALLOW_OFFLINE:
            print(
                f"⚠️ gitleaks failed (exit {payload.returncode}); skipping check (offline mode)",
                file=sys.stderr,
            )
            results["gitleaks"] = OFFLINE_SENTINEL
        else:
            results["gitleaks"] = payload.stdout or "[]"
    else:
        results["gitleaks"] = "not-installed"
    return results


def write_reports(results: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "security_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

    def _status(value: Any, *, empty: str) -> str:
        if value == OFFLINE_SENTINEL:
            return "skipped"
        return "issues" if value != empty else "none"

    gitleaks_payload = results.get("gitleaks", "")
    gitleaks_has_leaks = '"leaks":' in gitleaks_payload if isinstance(gitleaks_payload, str) else bool(gitleaks_payload)
    if gitleaks_payload in {"not-installed", OFFLINE_SENTINEL}:
        gitleaks_summary = "skipped"
    else:
        gitleaks_summary = "issues" if gitleaks_has_leaks else "none"

    summary = (
        "## Security audit\n\n"
        f"- pip-audit: {_status(results['pip_audit'], empty='[]')}\n"
        f"- safety: {_status(results['safety'], empty='[]')}\n"
        f"- bandit: {_status(results['bandit'], empty='{}')}\n"
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


def has_high_findings(results: Dict[str, Any]) -> bool:
    pip_value = results.get("pip_audit", "")
    if pip_value == OFFLINE_SENTINEL:
        return False

    pip_payload = _load_json(pip_value, [])
    for entry in pip_payload if isinstance(pip_payload, list) else []:
        for vuln in entry.get("vulns", []):
            if vuln.get("severity", "").upper() in {"HIGH", "CRITICAL"}:
                return True

    safety_value = results.get("safety", "")
    safety_payload = _load_json(safety_value, []) if safety_value != OFFLINE_SENTINEL else []
    for finding in _iter_safety_findings(safety_payload):
        if finding.get("severity", "").upper() in {"HIGH", "CRITICAL"}:
            return True

    bandit_value = results.get("bandit", "")
    bandit_payload = _load_json(bandit_value, {}) if bandit_value != OFFLINE_SENTINEL else {}
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
