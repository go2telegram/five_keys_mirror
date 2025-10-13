"""Entry-point for the CI audit workflow.

The script analyses open pull requests, re-runs failed checks, applies
small automatic fixes and produces aggregated reports in Markdown and JSON
formats. It is intentionally conservative to keep the API surface minimal
while providing useful automation hooks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import requests

from .autofix import AutoFixResult, apply_autofixes

LOGGER = logging.getLogger("ci_audit")
DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_SINCE_DAYS = 14

CATEGORY_ORDER = ["lint", "test", "security", "smoke"]
CATEGORY_TITLES = {
    "lint": "Lint",
    "test": "Tests",
    "security": "Security",
    "smoke": "Smoke",
}
STATUS_ICONS = {
    "pass": "✅",
    "fail": "❌",
    "pending": "⏳",
    "missing": "—",
}

KNOWN_FAILURE_KEYWORDS = {
    "lint": ["ruff", "format"],
    "security": ["gitleaks", "security audit", "pip-audit", "safety"],
    "imports": ["modulenotfounderror", "no module named", "tools"],
}


class GitHubError(RuntimeError):
    """Raised when the GitHub API returns an unexpected response."""


@dataclass
class CheckInfo:
    category: str
    name: str
    status: str
    conclusion: str | None
    url: str | None
    summary: str | None = None
    text: str | None = None

    def normalized_status(self) -> str:
        if self.conclusion in {"success", "neutral"}:
            return "pass"
        if self.conclusion in {"failure", "timed_out", "cancelled"}:
            return "fail"
        if self.status in {"queued", "in_progress"}:
            return "pending"
        return "missing"


@dataclass
class PRAuditResult:
    number: int
    title: str
    html_url: str
    head_sha: str
    author: str | None
    checks: dict[str, CheckInfo] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    issue_types: set[str] = field(default_factory=set)
    label: str | None = None
    comment: str | None = None

    def summary_row(self) -> list[str]:
        cells = [f"[{self.title}](%s)" % self.html_url]
        for category in CATEGORY_ORDER:
            info = self.checks.get(category)
            if not info:
                cells.append(STATUS_ICONS["missing"])
                continue
            cells.append(STATUS_ICONS.get(info.normalized_status(), "?"))
        cells.append("; ".join(self.actions) if self.actions else "—")
        cells.append(self.label or "—")
        return cells


class GitHubClient:
    """Minimal GitHub REST API wrapper."""

    def __init__(self, repo: str, token: str | None = None) -> None:
        self.repo = repo
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        if not self.token:
            LOGGER.warning("No GitHub token provided: running in read-only mode")

    # -- request helpers -------------------------------------------------
    def _headers(self) -> Mapping[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API error {response.status_code}: {response.text}")
        return response

    # -- pagination helpers ----------------------------------------------
    def _paginate(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            params = kwargs.setdefault("params", {}).copy()
            params["per_page"] = 100
            params["page"] = page
            kwargs["params"] = params
            response = self._request(method, path, **kwargs)
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubError("Expected list payload from GitHub API")
            if not payload:
                break
            yield from payload
            if "next" not in response.links:
                break
            page += 1

    # -- public API ------------------------------------------------------
    def iter_pull_requests(self) -> Iterator[dict[str, Any]]:
        yield from self._paginate("GET", f"/repos/{self.repo}/pulls", params={"state": "open"})

    def check_runs(self, sha: str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/repos/{self.repo}/commits/{sha}/check-runs")
        payload = response.json()
        runs = payload.get("check_runs", []) if isinstance(payload, dict) else []
        return runs if isinstance(runs, list) else []

    def check_run_details(self, run_id: int) -> dict[str, Any]:
        response = self._request("GET", f"/repos/{self.repo}/check-runs/{run_id}")
        return response.json()

    def rerequest_check_run(self, run_id: int) -> None:
        if not self.token:
            LOGGER.info("Skipping re-run for %s (no token)", run_id)
            return
        self._request("POST", f"/repos/{self.repo}/check-runs/{run_id}/rerequest")

    def replace_labels(self, pr_number: int, labels: Iterable[str]) -> None:
        if not self.token:
            LOGGER.info("Skipping label update for #%s (no token)", pr_number)
            return
        data = {"labels": list(labels)}
        self._request("PUT", f"/repos/{self.repo}/issues/{pr_number}/labels", json=data)

    def post_comment(self, pr_number: int, message: str) -> None:
        if not self.token:
            LOGGER.info("Skipping comment for #%s (no token)", pr_number)
            return
        data = {"body": message}
        self._request("POST", f"/repos/{self.repo}/issues/{pr_number}/comments", json=data)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit CI status across pull requests")
    parser.add_argument("--repo", required=True, help="Target repository in <owner>/<name> format")
    parser.add_argument(
        "--apply-fixes", action="store_true", help="Apply autofixes for known issues"
    )
    parser.add_argument("--re-run", action="store_true", help="Re-run failed checks when possible")
    parser.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS)
    parser.add_argument("--post-comments", action="store_true", help="Post status comments in PRs")
    parser.add_argument(
        "--label-prs", action="store_true", help="Update PR labels based on results"
    )
    parser.add_argument("--reports-dir", type=Path, default=Path("build/reports"))
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s: %(message)s"
    )


def _categorize(name: str) -> str | None:
    lname = name.lower()
    if "lint" in lname or "ruff" in lname:
        return "lint"
    if "test" in lname or "pytest" in lname:
        return "test"
    if "security" in lname or "gitleaks" in lname or "audit" in lname:
        return "security"
    if "smoke" in lname or "deploy" in lname or "dev" in lname:
        return "smoke"
    return None


def _match_known_issue(text: str | None) -> set[str]:
    if not text:
        return set()
    lower = text.lower()
    hits: set[str] = set()
    for key, patterns in KNOWN_FAILURE_KEYWORDS.items():
        if any(pattern in lower for pattern in patterns):
            hits.add(key)
    # imports is a special case -> map to test failures
    if "imports" in hits:
        hits.remove("imports")
        hits.add("imports")
        hits.add("test")
    return hits


def _should_include(pr: Mapping[str, Any], *, since_days: int) -> bool:
    updated_at = pr.get("updated_at")
    if not updated_at:
        return True
    try:
        updated = dt.datetime.strptime(updated_at, DATE_FMT)
    except ValueError:
        return True
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=since_days)
    return updated >= cutoff


def _format_actions(actions: Iterable[str]) -> str:
    return "; ".join(actions) if actions else "—"


def _determine_label(result: PRAuditResult) -> str:
    all_status = [info.normalized_status() for info in result.checks.values()]
    if all_status and all(status == "pass" for status in all_status):
        return "ci:ready"
    if result.issue_types:
        return "ci:needs-fix"
    return "ci:manual-review"


def _build_comment(result: PRAuditResult) -> str:
    lines = ["🧪 CI audit summary"]
    for category in CATEGORY_ORDER:
        info = result.checks.get(category)
        title = CATEGORY_TITLES[category]
        if info:
            status = STATUS_ICONS.get(info.normalized_status(), "?")
            detail = info.summary or info.text or ""
        else:
            status = STATUS_ICONS["missing"]
            detail = ""
        lines.append(f"- {status} {title}: {detail}")
    if result.actions:
        lines.append(f"Действия: {_format_actions(result.actions)}")
    if result.issue_types:
        lines.append(f"Автофиксы: {', '.join(sorted(result.issue_types))}")
    if result.comment:
        lines.append("")
        lines.append(result.comment)
    return "\n".join(lines)


def _save_reports(results: list[PRAuditResult], reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcnow().strftime(DATE_FMT)

    table_header = ["PR", *[CATEGORY_TITLES[c] for c in CATEGORY_ORDER], "Действия", "Итог"]
    rows = [
        "| " + " | ".join(table_header) + " |",
        "| " + " | ".join(["---"] * len(table_header)) + " |",
    ]
    for result in results:
        row = result.summary_row()
        rows.append("| " + " | ".join(row) + " |")
    markdown = "\n".join(rows)
    (reports_dir / "ci_audit.md").write_text(markdown, encoding="utf-8")

    json_payload = {
        "generated_at": timestamp,
        "pull_requests": [
            {
                "number": result.number,
                "title": result.title,
                "url": result.html_url,
                "label": result.label,
                "actions": result.actions,
                "checks": {
                    key: {
                        "name": info.name,
                        "status": info.normalized_status(),
                        "summary": info.summary,
                        "text": info.text,
                    }
                    for key, info in result.checks.items()
                },
            }
            for result in results
        ],
    }
    (reports_dir / "ci_audit.json").write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def audit_pull_requests(args: argparse.Namespace) -> list[PRAuditResult]:
    client = GitHubClient(args.repo)
    results: list[PRAuditResult] = []

    for pr in client.iter_pull_requests():
        if not _should_include(pr, since_days=args.since_days):
            continue
        number = pr.get("number")
        title = pr.get("title", f"PR #{number}")
        html_url = pr.get("html_url", "")
        head = pr.get("head", {})
        author = (pr.get("user") or {}).get("login")
        sha = head.get("sha", "")
        LOGGER.info("Analyzing PR #%s %s", number, title)
        result = PRAuditResult(
            number=number, title=title, html_url=html_url, head_sha=sha, author=author
        )

        runs = client.check_runs(sha)
        if not runs:
            LOGGER.warning("No check runs found for PR #%s", number)
        for run in runs:
            category = _categorize(run.get("name", ""))
            if not category:
                continue
            info = CheckInfo(
                category=category,
                name=run.get("name", category),
                status=run.get("status", ""),
                conclusion=run.get("conclusion"),
                url=run.get("html_url"),
            )
            result.checks[category] = info
            if info.normalized_status() == "fail":
                details = client.check_run_details(run.get("id")) if run.get("id") else {}
                output = details.get("output") if isinstance(details, dict) else None
                summary = output.get("summary") if isinstance(output, dict) else None
                text = output.get("text") if isinstance(output, dict) else None
                info.summary = summary
                info.text = text
                hits = _match_known_issue(" ".join(filter(None, [summary, text])))
                result.issue_types.update(hits)
                if args.re_run:
                    try:
                        client.rerequest_check_run(run["id"])
                        result.actions.append(f"rerun:{info.name}")
                    except Exception as exc:  # pragma: no cover - network errors
                        LOGGER.error("Failed to re-run %s: %s", info.name, exc)

        if args.apply_fixes and result.issue_types:
            fix_result: AutoFixResult = apply_autofixes(result.issue_types)
            if fix_result.applied:
                result.actions.extend(f"fix:{item}" for item in fix_result.applied)
            if fix_result.skipped:
                LOGGER.debug("Autofix skipped items: %s", fix_result.skipped)

        result.label = _determine_label(result)
        if args.label_prs:
            try:
                client.replace_labels(number, [result.label])
            except Exception as exc:  # pragma: no cover
                LOGGER.error("Unable to update labels for #%s: %s", number, exc)
        if args.post_comments:
            try:
                client.post_comment(number, _build_comment(result))
            except Exception as exc:  # pragma: no cover
                LOGGER.error("Unable to post comment for #%s: %s", number, exc)

        results.append(result)

    return results


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.log_level)
    try:
        results = audit_pull_requests(args)
    except GitHubError as exc:
        LOGGER.error("GitHub error: %s", exc)
        return 2
    except requests.RequestException as exc:  # pragma: no cover - network errors
        LOGGER.error("Network error: %s", exc)
        return 3

    _save_reports(results, args.reports_dir)
    LOGGER.info("Generated CI audit reports for %d pull requests", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
