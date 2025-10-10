#!/usr/bin/env python3
"""Catalog link availability checker.

The checker validates two types of links referenced in the product catalog:

* ``order.velavie_link`` – the primary purchase links for every product.
* ``image``/``images`` – preview images that are rendered in the catalog UI.

Every unique URL is probed with an HTTP ``HEAD`` request. When the endpoint
responds with ``405 Method Not Allowed`` the checker automatically retries with
``GET``.  A JSON-lines log is appended to ``logs/catalog_linkcheck.log`` so that
the status can be surfaced in ``doctor`` and other diagnostics tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog" / "products.json"
DEFAULT_LOG_PATH = ROOT / "logs" / "catalog_linkcheck.log"

USER_AGENT = "five-keys-bot/catalog-linkcheck"
HTTP_TIMEOUT = 10
CONCURRENCY = 8


class CatalogLinkCheckError(RuntimeError):
    """Raised when the checker cannot operate due to configuration issues."""


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


@dataclass(slots=True)
class LinkTarget:
    """A single link that needs to be validated."""

    url: str
    contexts: list[str]


@dataclass(slots=True)
class LinkCheckResult:
    """Outcome of the availability probe for a single URL."""

    url: str
    status: int | None
    detail: str | None
    contexts: list[str]

    @property
    def ok(self) -> bool:
        status = self.status
        return status is not None and 200 <= status < 400


def load_catalog(path: Path | None = None) -> Mapping[str, object]:
    """Load the catalog JSON file into memory."""

    catalog_path = Path(path) if path is not None else CATALOG_PATH
    try:
        raw = catalog_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogLinkCheckError(f"Cannot read catalog file {catalog_path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogLinkCheckError(f"Catalog file {catalog_path} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise CatalogLinkCheckError("Catalog payload must be a JSON object")
    return payload


def extract_targets(payload: Mapping[str, object]) -> list[LinkTarget]:
    """Collect unique link targets from the catalog payload."""

    products = payload.get("products")
    if not isinstance(products, Sequence):
        return []

    url_contexts: dict[str, set[str]] = {}

    for product in products:
        if not isinstance(product, Mapping):
            continue
        product_id = str(product.get("id") or "unknown")

        order = product.get("order")
        if isinstance(order, Mapping):
            velavie = order.get("velavie_link")
            if isinstance(velavie, str) and velavie.startswith("http"):
                url_contexts.setdefault(velavie, set()).add(f"{product_id}:order")

        image = product.get("image")
        if isinstance(image, str) and image.startswith("http"):
            url_contexts.setdefault(image, set()).add(f"{product_id}:image:primary")

        images = product.get("images")
        if isinstance(images, Sequence):
            for index, item in enumerate(images):
                if isinstance(item, str) and item.startswith("http"):
                    url_contexts.setdefault(item, set()).add(
                        f"{product_id}:image:{index}"
                    )

    targets: list[LinkTarget] = []
    for url, contexts in sorted(url_contexts.items()):
        targets.append(LinkTarget(url=url, contexts=sorted(contexts)))
    return targets


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
                async with session.get(url, allow_redirects=True, headers=headers) as resp:
                    return resp.status, None
            except Exception as inner_exc:  # noqa: BLE001 - surfaced in logs
                return None, str(inner_exc)
        return exc.status, exc.message
    except asyncio.TimeoutError:
        return None, "timeout"
    except aiohttp.ClientError as exc:
        return None, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return None, str(exc)


async def run_checks(
    targets: Sequence[LinkTarget],
    *,
    session_factory: Callable[[], aiohttp.ClientSession] | None = None,
    requester: Callable[[aiohttp.ClientSession, LinkTarget], tuple[int | None, str | None]]
    | None = None,
    concurrency: int = CONCURRENCY,
) -> list[LinkCheckResult]:
    """Run availability checks for all provided targets."""

    if not targets:
        return []

    factory: Callable[[], aiohttp.ClientSession]
    if session_factory is None:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        def factory() -> aiohttp.ClientSession:
            return aiohttp.ClientSession(timeout=timeout)

    else:
        factory = session_factory

    async def default_requester(
        session: aiohttp.ClientSession, target: LinkTarget
    ) -> tuple[int | None, str | None]:
        return await _perform_request(session, target.url)

    request = requester or default_requester
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async with factory() as session:
        async def worker(target: LinkTarget) -> LinkCheckResult:
            async with semaphore:
                status, detail = await request(session, target)
                return LinkCheckResult(
                    url=target.url,
                    status=status,
                    detail=detail,
                    contexts=list(target.contexts),
                )

        return await asyncio.gather(*(worker(target) for target in targets))


def summarise(
    results: Sequence[LinkCheckResult],
    *,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[dict[str, object], list[LinkCheckResult]]:
    """Build a machine-readable summary and extract problematic links."""

    problems = [result for result in results if not result.ok]
    total = len(results)
    status = "ok" if not problems else "warn"
    duration = max(0.0, finished_at.timestamp() - started_at.timestamp())
    summary: dict[str, object] = {
        "ts": started_at.isoformat(),
        "finished": finished_at.isoformat(),
        "status": status,
        "total": total,
        "broken": len(problems),
        "duration": round(duration, 2),
    }
    return summary, problems


def append_log(
    summary: Mapping[str, object],
    problems: Sequence[LinkCheckResult],
    *,
    log_path: Path | None = None,
) -> None:
    """Append a JSON-lines report for the run to the log file."""

    target_path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        json.dumps(
            {
                "kind": "summary",
                **summary,
            },
            ensure_ascii=False,
        )
    ]
    for problem in problems:
        lines.append(
            json.dumps(
                {
                    "kind": "problem",
                    "ts": summary.get("ts"),
                    "url": problem.url,
                    "status": problem.status,
                    "detail": problem.detail,
                    "contexts": problem.contexts,
                },
                ensure_ascii=False,
            )
        )

    with target_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=CATALOG_PATH,
        help="Path to products.json",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Path to the JSON-lines log file",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=CONCURRENCY,
        help="Maximum number of concurrent HTTP requests",
    )
    parser.add_argument(
        "--no-net",
        action="store_true",
        help="Skip network calls (records a skipped summary)",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.no_net or os.getenv("NO_NET") == "1":
        now = datetime.now(timezone.utc)
        log_relative = _relative_to_root(Path(args.log))
        summary = {
            "ts": now.isoformat(),
            "finished": now.isoformat(),
            "status": "skip",
            "total": 0,
            "broken": 0,
            "duration": 0.0,
            "log": log_relative,
            "reason": "NO_NET",
        }
        append_log(summary, [], log_path=args.log)
        return 0, summary

    payload = load_catalog(args.catalog)
    targets = extract_targets(payload)

    if not targets:
        now = datetime.now(timezone.utc)
        log_relative = _relative_to_root(Path(args.log))
        summary = {
            "ts": now.isoformat(),
            "finished": now.isoformat(),
            "status": "warn",
            "total": 0,
            "broken": 0,
            "duration": 0.0,
            "log": log_relative,
            "reason": "no_targets",
        }
        append_log(summary, [], log_path=args.log)
        return 1, summary

    started = datetime.now(timezone.utc)

    def session_factory() -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        return aiohttp.ClientSession(timeout=timeout)

    results = await run_checks(
        targets,
        session_factory=session_factory,
        concurrency=max(1, args.concurrency),
    )
    finished = datetime.now(timezone.utc)
    summary, problems = summarise(results, started_at=started, finished_at=finished)
    log_relative = _relative_to_root(Path(args.log))
    summary = {**summary, "log": log_relative}
    append_log(summary, problems, log_path=args.log)

    if problems:
        for problem in problems[:20]:
            ctx = ", ".join(problem.contexts)
            status = problem.status if problem.status is not None else "ERR"
            detail = f" ({problem.detail})" if problem.detail else ""
            print(f"BROKEN {status} {problem.url} [{ctx}]{detail}")

    total = summary.get("total", 0)
    broken = summary.get("broken", 0)
    duration = summary.get("duration", 0.0)
    print(
        f"SUMMARY status={summary['status']} total={total} broken={broken} "
        f"duration={duration}s log={summary['log']}"
    )

    exit_code = 0 if not problems else 1
    return exit_code, summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        exit_code, summary = asyncio.run(_async_main(args))
    except CatalogLinkCheckError as exc:
        print(f"ERROR {exc}")
        log_relative = _relative_to_root(Path(args.log))
        summary = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "message": str(exc),
            "log": log_relative,
        }
        append_log(summary, [], log_path=args.log)
        return 2

    print(json.dumps(summary, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
