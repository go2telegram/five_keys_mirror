#!/usr/bin/env python3
"""Perform HEAD checks for catalog and quiz images."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - optional dependency for quiz parsing
    import yaml
except ModuleNotFoundError:  # pragma: no cover - handled gracefully below
    yaml = None  # type: ignore[assignment]

from app.config import settings  # noqa: E402

CATALOG_FILE = ROOT / "app" / "catalog" / "products.json"
QUIZ_DATA_DIR = ROOT / "app" / "quiz" / "data"
REPORT_PATH = ROOT / "build" / "images_head_report.txt"

USER_AGENT = "five-keys-bot/head-check"
DEFAULT_TIMEOUT = 10


def main() -> int:
    if os.getenv("NO_NET", "0") == "1":
        print("NO_NET=1 -> skip head checks")
        return 0

    urls = set(_collect_product_urls())
    urls.update(_collect_quiz_urls())

    if not urls:
        print("WARN No image URLs discovered; report will be empty.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, str, str | None]] = []
    for url in sorted(urls):
        status, detail = _head_request(url)
        results.append((status, url, detail))

    _write_report(results)
    _print_summary(results)
    return 0


def _collect_product_urls() -> Iterable[str]:
    if not CATALOG_FILE.exists():
        print(f"WARN Catalog file not found: {CATALOG_FILE}")
        return []

    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"WARN Cannot parse {CATALOG_FILE}: {exc}")
        return []

    products = data.get("products")
    if not isinstance(products, list):
        return []

    urls: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        image = product.get("image")
        if isinstance(image, str) and image.startswith("http"):
            urls.append(image)
            continue
        images = product.get("images")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
    return urls


def _collect_quiz_urls() -> Iterable[str]:
    base = (settings.QUIZ_IMG_BASE or "").rstrip("/")
    mode = (settings.QUIZ_IMAGE_MODE or "remote").strip().lower()
    if yaml is None:
        print("WARN PyYAML is not installed; skipping quiz image HEAD checks.")
        return []
    if not QUIZ_DATA_DIR.exists():
        print(f"WARN Quiz data directory missing: {QUIZ_DATA_DIR}")
        return []

    urls: list[str] = []
    for yaml_path in sorted(QUIZ_DATA_DIR.glob("*.yaml")):
        with yaml_path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        quiz_name = yaml_path.stem
        references = []
        cover = data.get("cover")
        if isinstance(cover, str):
            references.append((quiz_name, "cover", cover))
        for question in data.get("questions", []) or []:
            if not isinstance(question, dict):
                continue
            qid = str(question.get("id", "")) or "unknown"
            image_path = question.get("image")
            if isinstance(image_path, str):
                references.append((quiz_name, f"question:{qid}", image_path))
        for quiz, label, path in references:
            if path.startswith("http://") or path.startswith("https://"):
                urls.append(path)
            elif base:
                urls.append(f"{base}/{path.lstrip('/')}")
            else:
                print(
                    f"WARN [{quiz}] {label}: cannot build remote URL without QUIZ_IMG_BASE",
                )
            if mode == "local" and not path.startswith("http"):
                # In local mode we still collect the remote URL when possible for CI visibility.
                continue
    return urls


def _head_request(url: str) -> tuple[str, str | None]:
    request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response:  # type: ignore[arg-type]
            return str(getattr(response, "status", 200)), None
    except HTTPError as exc:
        if exc.code == 405:  # Method Not Allowed — retry with GET
            get_request = Request(url, method="GET", headers={"User-Agent": USER_AGENT})
            try:
                with urlopen(get_request, timeout=DEFAULT_TIMEOUT) as response:  # type: ignore[arg-type]
                    # We only need to trigger the request; the status code is enough.
                    return str(getattr(response, "status", 200)), None
            except Exception as inner_exc:  # pragma: no cover - network failures
                return "ERR", str(inner_exc)
        return str(exc.code), exc.reason if isinstance(exc.reason, str) else None
    except URLError as exc:  # pragma: no cover - network failures
        return "ERR", str(exc.reason)
    except Exception as exc:  # pragma: no cover - unexpected issues
        return "ERR", str(exc)


def _write_report(results: Iterable[tuple[str, str, str | None]]) -> None:
    lines = ["# Image HEAD check report", ""]
    for status, url, detail in results:
        if detail:
            lines.append(f"{status}\t{url}\t{detail}")
        else:
            lines.append(f"{status}\t{url}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(results: Iterable[tuple[str, str, str | None]]) -> None:
    counter = Counter(status for status, _, _ in results)
    total = sum(counter.values())
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counter.items()))
    print(f"HEAD check completed. Total={total}. Breakdown: {summary or 'none'}.")
    print(f"Report saved to {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
