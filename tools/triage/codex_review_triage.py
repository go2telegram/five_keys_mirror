import argparse
import base64
import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from . import matchers


API_URL = "https://api.github.com"
PR_LABEL_PREFIX = "triage:"
STATUS_LABELS = {
    "needs-fix": f"{PR_LABEL_PREFIX}needs-fix",
    "resolved": f"{PR_LABEL_PREFIX}resolved",
    "obsolete": f"{PR_LABEL_PREFIX}obsolete",
    "manual-review": f"{PR_LABEL_PREFIX}manual-review",
}


@dataclasses.dataclass
class ReviewComment:
    pr_number: int
    pr_url: str
    pr_state: str
    pr_merged: bool
    comment_id: int
    file_path: str
    body: str
    diff_hunk: str
    author: str


@dataclasses.dataclass
class CommentEvaluation:
    status: str
    reason: str
    presence: str
    presence_reason: str
    related_checks: Sequence[str]


@dataclasses.dataclass
class PullRequestReport:
    number: int
    url: str
    title: str
    comments: List[Dict[str, str]]
    label_statuses: Sequence[str]
    summary_counter: Counter


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/vnd.github+json"

    def graphql(self, query: str, variables: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        response = self.session.post(
            f"{API_URL}/graphql",
            json={"query": query, "variables": variables or {}},
        )
        if response.status_code != 200:
            raise RuntimeError(f"GraphQL query failed: {response.status_code} {response.text}")
        payload = response.json()
        if "errors" in payload:
            raise RuntimeError(f"GraphQL query errors: {payload['errors']}")
        return payload["data"]

    def rest_get(self, path: str, params: Optional[Dict[str, object]] = None) -> List[Dict[str, object]]:
        results: List[Dict[str, object]] = []
        url = f"{API_URL}{path}"
        while url:
            response = self.session.get(url, params=params)
            if response.status_code != 200:
                raise RuntimeError(f"GET {url} failed: {response.status_code} {response.text}")
            payload = response.json()
            if isinstance(payload, list):
                results.extend(payload)
            else:
                return payload
            url = response.links.get("next", {}).get("url")
            params = None
        return results

    def rest_post(self, path: str, data: Dict[str, object]) -> Dict[str, object]:
        response = self.session.post(f"{API_URL}{path}", json=data)
        if response.status_code >= 300:
            raise RuntimeError(f"POST {path} failed: {response.status_code} {response.text}")
        return response.json()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex review triage helper")
    parser.add_argument("--repo", required=True, help="Repository in the form owner/name")
    parser.add_argument("--since-days", type=int, default=30)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--labels", nargs="*", default=[])
    parser.add_argument("--apply-labels", action="store_true")
    parser.add_argument("--post-comments", action="store_true")
    return parser.parse_args(argv)


def compute_since_date(days: int) -> str:
    target = dt.datetime.utcnow() - dt.timedelta(days=days)
    return target.date().isoformat()


def build_search_query(repo: str, labels: Sequence[str], since: str) -> str:
    owner, name = repo.split("/", 1)
    label_fragments = [f'label:"{label}"' for label in labels]
    fragments = [f"repo:{owner}/{name}", "is:pr", f"updated:>={since}"] + label_fragments
    return " ".join(fragments)


def fetch_pull_requests(
    client: GitHubClient,
    repo: str,
    labels: Sequence[str],
    since_days: int,
) -> List[Dict[str, object]]:
    since = compute_since_date(since_days)
    query = build_search_query(repo, labels, since)
    has_next_page = True
    cursor: Optional[str] = None
    results: List[Dict[str, object]] = []
    while has_next_page:
        data = client.graphql(
            """
            query ($query: String!, $cursor: String) {
              search(query: $query, type: ISSUE, first: 50, after: $cursor) {
                issueCount
                pageInfo { hasNextPage endCursor }
                nodes {
                  ... on PullRequest {
                    number
                    title
                    url
                    state
                    merged
                    mergedAt
                    labels(first: 20) { nodes { name } }
                  }
                }
              }
            }
            """,
            {"query": query, "cursor": cursor},
        )
        search = data["search"]
        for node in search["nodes"]:
            if node is not None:
                results.append(node)
        has_next_page = search["pageInfo"]["hasNextPage"]
        cursor = search["pageInfo"].get("endCursor")
    return results


def fetch_review_comments(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    actor: str,
    pr_url: str,
    pr_state: str,
    pr_merged: bool,
) -> List[ReviewComment]:
    comments_data = client.rest_get(f"/repos/{repo}/pulls/{pr_number}/comments")
    results: List[ReviewComment] = []
    for item in comments_data:
        if item.get("user", {}).get("login") != actor:
            continue
        results.append(
            ReviewComment(
                pr_number=pr_number,
                pr_url=pr_url,
                pr_state=pr_state,
                pr_merged=pr_merged,
                comment_id=item["id"],
                file_path=item.get("path", ""),
                body=item.get("body", ""),
                diff_hunk=item.get("diff_hunk", ""),
                author=item.get("user", {}).get("login", ""),
            )
        )
    return results


def extract_excerpt(diff_hunk: str, body: str) -> str:
    if diff_hunk:
        lines = [line[1:] if line.startswith(("+", "-")) else line for line in diff_hunk.splitlines()]
        cleaned = [line.strip() for line in lines if line.strip()]
        if cleaned:
            return " ".join(cleaned[-5:])
    snippet = body.strip().splitlines()
    if snippet:
        return snippet[0][:200]
    return ""


def fetch_file_contents(client: GitHubClient, repo: str, path: str, ref: str = "main") -> Optional[str]:
    if not path:
        return None
    response = client.session.get(f"{API_URL}/repos/{repo}/contents/{path}", params={"ref": ref})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"Unable to load file {path} from {ref}: {response.status_code} {response.text}")
    payload = response.json()
    if payload.get("encoding") == "base64":
        return base64.b64decode(payload.get("content", "")).decode("utf-8", errors="ignore")
    if "content" in payload:
        return payload["content"]
    return None


def run_command(command: Sequence[str]) -> Tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
        return completed.returncode == 0, completed.stdout
    except FileNotFoundError as exc:
        return False, str(exc)


def execute_checks() -> Dict[str, Dict[str, object]]:
    checks: Dict[str, Dict[str, object]] = {}
    commands = {
        "build_products": [sys.executable, "-m", "tools.build_products", "validate"],
        "pytest": [sys.executable, "-m", "pytest", "-q"],
        "ruff": ["ruff", "check"],
        "bandit": ["bandit", "-q", "-r", "app", "-f", "json"],
        "head_check": [sys.executable, "tools/head_check.py"],
    }
    for name, command in commands.items():
        success, output = run_command(command)
        checks[name] = {"success": success, "output": output}
    return checks


def checks_failed(checks: Dict[str, Dict[str, object]], related: Sequence[str]) -> bool:
    if not related:
        return False
    return any(
        not checks.get(c, {"success": True})["success"]
        for c in related
    )


def determine_related_checks(comment: ReviewComment) -> List[str]:
    text = comment.body.lower()
    related: List[str] = []
    if any(keyword in text for keyword in ["lint", "ruff", "flake", "format"]):
        related.append("ruff")
    if any(keyword in text for keyword in ["security", "bandit", "vuln", "unsafe"]):
        related.append("bandit")
    if any(keyword in text for keyword in ["test", "pytest", "assert"]):
        related.append("pytest")
    if ".github/workflows" in comment.file_path or "workflow" in text:
        related.append("build_products")
    if "head" in text and "check" in text:
        related.append("head_check")
    return related


def classify_comment(
    comment: ReviewComment,
    excerpt: str,
    file_text: Optional[str],
    checks: Dict[str, Dict[str, object]],
) -> CommentEvaluation:
    related = determine_related_checks(comment)
    presence, presence_reason = matchers.evaluate_context(
        comment.file_path, comment.body, excerpt, file_text or ""
    )
    if presence == "manual":
        status = "manual-review"
        reason = "Requires manual confirmation of fuzzy match"
    elif presence in {"present", "maybe"}:
        status = "needs-fix"
        reason = f"Context still present ({presence})"
    else:  # absent
        if checks_failed(checks, related):
            status = "needs-fix"
            reason = "Related automated check is failing"
        elif comment.pr_merged:
            status = "obsolete"
            reason = "Pull request merged and context missing"
        else:
            status = "resolved"
            reason = "Context missing and checks green"
    return CommentEvaluation(
        status=status,
        reason=reason,
        presence=presence,
        presence_reason=presence_reason,
        related_checks=related,
    )


def ensure_build_reports_dir() -> Path:
    reports_dir = Path("build/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def build_markdown_report(pr_reports: Sequence[PullRequestReport]) -> str:
    lines = ["# Codex Review Triage", ""]
    total_counter = Counter()
    for report in pr_reports:
        total_counter.update(report.summary_counter)
    summary_parts = [f"{count} {status}" for status, count in total_counter.items()]
    if summary_parts:
        lines.append("Summary: " + ", ".join(summary_parts))
        lines.append("")
    lines.append("| PR | File | Excerpt | Status | Why |")
    lines.append("| --- | --- | --- | --- | --- |")
    for report in pr_reports:
        for comment in report.comments:
            lines.append(
                "| "
                f"[{report.number}]({report.url}) | "
                f"{comment['file']} | {comment['excerpt']} | "
                f"{comment['status']} | {comment['reason']} |"
            )
    return "\n".join(lines) + "\n"


def build_json_report(pr_reports: Sequence[PullRequestReport]) -> Dict[str, object]:
    return {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "pull_requests": [dataclasses.asdict(report) for report in pr_reports],
    }


def save_reports(pr_reports: Sequence[PullRequestReport]) -> Tuple[Path, Path]:
    reports_dir = ensure_build_reports_dir()
    md_content = build_markdown_report(pr_reports)
    json_content = build_json_report(pr_reports)
    md_path = reports_dir / "review_triage.md"
    json_path = reports_dir / "review_triage.json"
    md_path.write_text(md_content, encoding="utf-8")
    json_path.write_text(json.dumps(json_content, indent=2), encoding="utf-8")
    return md_path, json_path


def summarize_counts(counter: Counter) -> str:
    if not counter:
        return "no findings"
    ordering = ["needs-fix", "manual-review", "obsolete", "resolved"]
    parts = []
    for status in ordering:
        if status in counter:
            parts.append(f"{counter[status]} {status}")
    for status in counter:
        if status not in ordering:
            parts.append(f"{counter[status]} {status}")
    return ", ".join(parts)


def apply_labels(client: GitHubClient, repo: str, pr_number: int, statuses: Iterable[str]) -> None:
    labels = sorted({STATUS_LABELS[status] for status in statuses if status in STATUS_LABELS})
    if not labels:
        return
    client.rest_post(f"/repos/{repo}/issues/{pr_number}/labels", {"labels": labels})


def post_summary_comment(client: GitHubClient, repo: str, pr_number: int, summary: str, report_path: Path) -> None:
    body = (
        f"Автотриаж: {summary}. Полный отчёт: artifact `{report_path}`."
    )
    client.rest_post(f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    client = GitHubClient(token)
    repo = args.repo
    prs = fetch_pull_requests(client, repo, args.labels, args.since_days)
    if not prs:
        print("No pull requests found for triage")
        return 0

    checks = execute_checks()
    pr_reports: List[PullRequestReport] = []
    for pr in prs:
        pr_number = pr["number"]
        comments = fetch_review_comments(
            client,
            repo,
            pr_number,
            args.actor,
            pr.get("url", ""),
            pr.get("state", ""),
            bool(pr.get("merged", False)),
        )
        if not comments:
            continue
        comment_rows: List[Dict[str, str]] = []
        pr_counter: Counter = Counter()
        for comment in comments:
            excerpt = extract_excerpt(comment.diff_hunk, comment.body)
            file_text = fetch_file_contents(client, repo, comment.file_path)
            evaluation = classify_comment(comment, excerpt, file_text, checks)
            pr_counter[evaluation.status] += 1
            comment_rows.append(
                {
                    "comment_id": str(comment.comment_id),
                    "file": comment.file_path or "(no file)",
                    "excerpt": excerpt,
                    "status": evaluation.status,
                    "reason": evaluation.reason,
                    "presence": evaluation.presence,
                    "presence_reason": evaluation.presence_reason,
                    "related_checks": ", ".join(evaluation.related_checks) or "-",
                }
            )
        if not comment_rows:
            continue
        pr_reports.append(
            PullRequestReport(
                number=pr_number,
                url=pr["url"],
                title=pr.get("title", ""),
                comments=comment_rows,
                label_statuses=list(pr_counter.keys()),
                summary_counter=pr_counter,
            )
        )

    if not pr_reports:
        print("No relevant review comments found")
        return 0

    md_path, _ = save_reports(pr_reports)

    if args.apply_labels or args.post_comments:
        for report in pr_reports:
            if args.apply_labels:
                apply_labels(client, repo, report.number, report.label_statuses)
            if args.post_comments:
                summary = summarize_counts(report.summary_counter)
                post_summary_comment(client, repo, report.number, summary, md_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
