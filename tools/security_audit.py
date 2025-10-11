import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
from typing import Any, Dict, Iterable, Tuple

REPORTS_DIR = pathlib.Path("build/reports")

logger = logging.getLogger(__name__)


def run_command(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, text=True, capture_output=True)


def collect_reports() -> Tuple[Dict[str, Any], bool]:
    results: Dict[str, Any] = {}
    results["pip_audit"] = run_command("pip-audit -r requirements.txt -f json").stdout or "[]"
    results["safety"] = run_command("safety check --full-report -r requirements.txt --json").stdout or "[]"
    results["bandit"] = run_command("bandit -q -r app -f json").stdout or "{}"
    gitleaks_payload, gitleaks_missing = run_gitleaks_scan()
    results["gitleaks"] = gitleaks_payload
    return results, gitleaks_missing


GITLEAKS_SKIP_MESSAGE = "⚠️ Skipping gitleaks (binary not found)"


def _should_skip_on_missing() -> bool:
    value = os.getenv("GITLEAKS_SKIP_ON_MISSING")
    if value is None:
        return True
    value = value.strip().lower()
    return value not in {"", "0", "false", "no"}


def run_gitleaks_scan() -> Tuple[str, bool]:
    command = [
        "gitleaks",
        "detect",
        "--no-git",
        "-f",
        "json",
        "--redact",
        "--exit-code",
        "0",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
        )
    except (FileNotFoundError, OSError) as exc:
        logger.debug("gitleaks execution failed: %s", exc)
        return "not-installed", True

    stdout = completed.stdout or ""
    if completed.returncode != 0:
        if "no leaks found" in stdout.lower():
            return stdout or "[]", False
        if completed.stderr:
            logger.debug("gitleaks stderr: %s", completed.stderr.strip())
        return stdout or "[]", False
    return stdout or "[]", False


def write_reports(results: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "security_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    gitleaks_payload = results.get("gitleaks", "")
    gitleaks_has_leaks = '"leaks":' in gitleaks_payload if isinstance(gitleaks_payload, str) else bool(gitleaks_payload)
    if gitleaks_payload == "not-installed":
        gitleaks_summary = "skipped"
    else:
        gitleaks_summary = "issues" if gitleaks_has_leaks else "none"

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

    reports, gitleaks_missing = collect_reports()
    summary = write_reports(reports)

    if args.summary:
        print(summary, end="")

    exit_code = 1 if has_high_findings(reports) else 0

    if gitleaks_missing and _should_skip_on_missing():
        print(GITLEAKS_SKIP_MESSAGE)
        return 0

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
