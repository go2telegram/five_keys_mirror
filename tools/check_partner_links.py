"""Partner link health check utility.

The script walks through two link sources:

* The historical register exported from Telegram (``topics.csv``).
* The active set that is used in the bot navigation (``app.handlers.navigator``).

Each URL is validated with an HTTP ``HEAD`` request (falling back to ``GET`` when
needed). A human-readable report is stored at
``build/reports/links_head_report.txt``. When the ``--previous`` option is
supplied the report from the previous run is parsed so the tool can highlight
newly broken links while ignoring the ones that were already failing.

The module is intentionally importable so that we can unit-test the core logic
without performing real network calls.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import argparse
import asyncio
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPORT_PATH = ROOT / "build" / "reports" / "links_head_report.txt"
DEFAULT_DIFF_JSON = ROOT / "build" / "reports" / "links_head_diff.json"
DEFAULT_REGISTER_PATH = (
    ROOT
    / "Вспомогательное"
    / "Сборшик постов с группы и канала"
    / "mito_export"
    / "topics.csv"
)

USER_AGENT = "five-keys-bot/link-health"
HTTP_TIMEOUT = 6
CONCURRENCY = 8


@dataclass(slots=True)
class PartnerLink:
    """Representation of a partner link."""

    url: str
    title: str | None
    source: str


@dataclass(slots=True)
class LinkCheckResult:
    """Result of the HEAD check for a single link."""

    link: PartnerLink
    status: int | None
    detail: str | None

    @property
    def ok(self) -> bool:
        status = self.status
        return status is not None and 200 <= status < 400


@dataclass(slots=True)
class LinkCheckOutcome:
    """Container with all aggregated results."""

    results: list[LinkCheckResult]
    problems: list[LinkCheckResult]
    new_problems: list[LinkCheckResult]
    resolved: list[str]
    report_path: Path
    diff_json_path: Path | None
    skipped: bool = False

    @property
    def total(self) -> int:
        return len(self.results)


SessionFactory = Callable[..., aiohttp.ClientSession]


def collect_register_links(path: Path | None = None) -> list[PartnerLink]:
    """Collect links from the exported Telegram register."""

    register_path = Path(
        os.getenv("PARTNER_REGISTER_PATH", str(path or DEFAULT_REGISTER_PATH))
    )
    if not register_path.exists():
        print(f"WARN Register file not found: {register_path}")
        return []

    links: list[PartnerLink] = []
    try:
        with register_path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url or not url.startswith("http"):
                    continue
                title = (row.get("topic_title") or "").strip() or None
                links.append(PartnerLink(url=url, title=title, source="register"))
    except Exception as exc:  # noqa: BLE001 - log and continue
        print(f"WARN Cannot parse register at {register_path}: {exc}")
    return links


def collect_active_links() -> list[PartnerLink]:
    """Collect partner links that are actively used in the bot."""

    links: list[PartnerLink] = []
    try:
        from app.handlers import navigator  # type: ignore import-not-found
    except Exception as exc:  # noqa: BLE001 - optional dependency for the tool
        print(f"WARN Cannot import navigator links: {exc}")
        return links

    nav = getattr(navigator, "NAV", {})
    if not isinstance(nav, dict):
        return links

    for category_key, payload in nav.items():
        title = str(payload.get("title", "")).strip() if isinstance(payload, dict) else ""
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, Iterable):
            continue
        for entry in items:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            item_title, url = entry
            url_str = str(url).strip()
            if not url_str.startswith("http"):
                continue
            links.append(
                PartnerLink(
                    url=url_str,
                    title=str(item_title).strip() or title or None,
                    source=f"active:navigator:{category_key}",
                )
            )
    return links


def collect_all_links() -> list[PartnerLink]:
    """Collect and de-duplicate partner links from all sources."""

    links: list[PartnerLink] = []
    seen: set[str] = set()

    for link in collect_register_links():
        if link.url not in seen:
            links.append(link)
            seen.add(link.url)

    for link in collect_active_links():
        if link.url not in seen:
            links.append(link)
            seen.add(link.url)

    return links


async def _perform_request(
    session: aiohttp.ClientSession, url: str
) -> tuple[int | None, str | None]:
    headers = {"User-Agent": USER_AGENT}
    try:
        async with session.head(url, allow_redirects=True, headers=headers) as resp:
            return resp.status, None
    except aiohttp.ClientResponseError as exc:
        if exc.status == 405:
            try:
                async with session.get(
                    url, allow_redirects=True, headers=headers
                ) as resp:
                    return resp.status, None
            except Exception as inner_exc:  # noqa: BLE001
                return None, str(inner_exc)
        return exc.status, exc.message
    except asyncio.TimeoutError:
        return None, "timeout"
    except aiohttp.ClientError as exc:
        return None, str(exc)


async def run_checks(
    links: Sequence[PartnerLink],
    *,
    session_factory: SessionFactory | None = None,
) -> list[LinkCheckResult]:
    if not links:
        return []

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    factory = session_factory or (lambda **kw: aiohttp.ClientSession(**kw))

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with factory(timeout=timeout) as session:  # type: ignore[func-returns-value]
        tasks = []

        async def _run(link: PartnerLink) -> LinkCheckResult:
            async with semaphore:
                status, detail = await _perform_request(session, link.url)
                return LinkCheckResult(link=link, status=status, detail=detail)

        for link in links:
            tasks.append(_run(link))

        return await asyncio.gather(*tasks)


def _parse_report(path: Path) -> dict[str, int | None]:
    if not path.exists():
        return {}

    mapping: dict[str, int | None] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            _, status_str, url, *_rest = parts
            status: int | None
            if status_str.upper() in {"ERR", "ERROR"}:
                status = None
            else:
                try:
                    status = int(status_str)
                except ValueError:
                    status = None
            mapping[url] = status
    return mapping


def _is_ok(status: int | None) -> bool:
    return status is not None and 200 <= status < 400


def _write_report(results: Sequence[LinkCheckResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Partner link HEAD report", "# source\tstatus\turl\ttitle\tdetail"]
    for result in results:
        title = result.link.title or ""
        detail = result.detail or ""
        safe_title = title.replace("\t", " ").replace("\n", " ")
        safe_detail = detail.replace("\t", " ").replace("\n", " ")
        status = "ERR" if result.status is None else str(result.status)
        lines.append(
            "\t".join(
                [result.link.source, status, result.link.url, safe_title, safe_detail]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_diff_json(
    *,
    new: Sequence[LinkCheckResult],
    resolved: Sequence[str],
    path: Path,
) -> None:
    payload = {
        "new": [
            {
                "url": item.link.url,
                "status": item.status,
                "detail": item.detail,
                "title": item.link.title,
                "source": item.link.source,
            }
            for item in new
        ],
        "resolved": list(resolved),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _send_notification(new_items: Sequence[LinkCheckResult]) -> None:
    token = os.getenv("LINK_HEALTH_BOT_TOKEN") or os.getenv("LINKS_REPORT_BOT_TOKEN")
    chat_id = os.getenv("LINK_HEALTH_CHAT_ID") or os.getenv("LINKS_REPORT_CHAT_ID")
    if not token or not chat_id:
        print("INFO Notification skipped: LINK_HEALTH_BOT_TOKEN/CHAT_ID not configured")
        return

    lines = ["⚠️ Обнаружены новые проблемы с партнёрскими ссылками:"]
    for item in new_items:
        status = "ERR" if item.status is None else str(item.status)
        detail = f" ({item.detail})" if item.detail else ""
        title = item.link.title or item.link.url
        lines.append(f"• {title}: {status}{detail}")
        lines.append(item.link.url)
    text = "\n".join(lines)

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    print(
                        f"WARN Failed to send notification: status={response.status} body={body}",
                    )
    except Exception as exc:  # noqa: BLE001 - network failure should not abort the job
        print(f"WARN Notification failed: {exc}")


async def execute(
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
    previous_report: Path | None = None,
    diff_json_path: Path | None = DEFAULT_DIFF_JSON,
    notify: bool = False,
    session_factory: SessionFactory | None = None,
) -> LinkCheckOutcome:
    if os.getenv("NO_NET") == "1":
        print("NO_NET=1 -> skip partner link head checks")
        return LinkCheckOutcome(
            results=[],
            problems=[],
            new_problems=[],
            resolved=[],
            report_path=report_path,
            diff_json_path=diff_json_path,
            skipped=True,
        )

    links = collect_all_links()
    print(f"INFO Checking {len(links)} partner links...")

    previous = _parse_report(previous_report) if previous_report else {}

    results = await run_checks(links, session_factory=session_factory)
    problems = [item for item in results if not item.ok]

    current_problem_urls = {item.link.url: item for item in problems}
    previous_problem_urls = {
        url: status for url, status in previous.items() if not _is_ok(status)
    }

    new_problems = [
        item
        for url, item in current_problem_urls.items()
        if url not in previous_problem_urls
    ]
    resolved = [
        url for url in previous_problem_urls if url not in current_problem_urls
    ]

    _write_report(results, report_path)
    if diff_json_path is not None:
        _write_diff_json(new=new_problems, resolved=resolved, path=diff_json_path)

    ok_count = sum(1 for item in results if item.ok)
    print(
        f"INFO Partner link check completed: ok={ok_count}, problems={len(problems)}"
    )
    try:
        rel_report = report_path.relative_to(ROOT)
    except ValueError:
        rel_report = report_path
    print(f"INFO Report saved to {rel_report}")

    if new_problems:
        print(
            "WARN New problematic links detected: "
            + ", ".join(item.link.url for item in new_problems)
        )

    if resolved:
        print("INFO Resolved link issues: " + ", ".join(resolved))

    if notify and new_problems:
        await _send_notification(new_problems)

    return LinkCheckOutcome(
        results=results,
        problems=problems,
        new_problems=new_problems,
        resolved=resolved,
        report_path=report_path,
        diff_json_path=diff_json_path,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Partner link HEAD checker")
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to write the report to (default: build/reports/links_head_report.txt)",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        default=None,
        help="Optional path to the previous report to compute deltas",
    )
    parser.add_argument(
        "--diff-json",
        dest="diff_json",
        type=Path,
        default=DEFAULT_DIFF_JSON,
        help="Optional path to store a JSON diff with new/resolved issues",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send a Telegram notification when new problems are detected",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        outcome = asyncio.run(
            execute(
                report_path=args.report,
                previous_report=args.previous,
                diff_json_path=args.diff_json,
                notify=args.notify,
            )
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive usage
        return 130

    if outcome.skipped:
        return 0

    if os.getenv("GITHUB_ACTIONS") == "true":
        try:
            rel = outcome.report_path.relative_to(ROOT)
        except ValueError:
            rel = outcome.report_path
        print(f"::notice file={rel}::Partner link report generated")

    # We intentionally keep the exit code at zero so the step is warn-only.
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
