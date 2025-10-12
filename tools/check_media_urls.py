import argparse
import asyncio
import glob
import json
import os
from pathlib import Path

import aiohttp
import yaml

REPORT_PATH = Path("build/reports/media_head_report.txt")


async def head(url: str):
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.head(url, allow_redirects=True) as response,
        ):
            return url, response.status, response.headers.get("Content-Type", "")
    except Exception as exc:  # noqa: BLE001 - network errors reported in summary
        return url, -1, str(exc)


async def collect_urls():
    urls = set()

    with open("app/catalog/products.json", encoding="utf-8") as fp:
        data = json.load(fp)
    items = data["products"] if isinstance(data, dict) else data
    for product in items:
        image = product.get("image") or (product.get("images") or [None])[0]
        if image and image.startswith("http"):
            urls.add(image)

    for path in glob.glob("app/quiz/data/*.yaml"):
        with open(path, encoding="utf-8") as handle:
            yml = yaml.safe_load(handle)

        base = os.getenv("QUIZ_IMG_BASE", "")

        def norm(url: str, base: str = base):
            return url if url.startswith("http") else f"{base.rstrip('/')}/{url.lstrip('/')}"

        cover = yml.get("cover")
        images = [question.get("image") for question in yml.get("questions", [])]

        for url in [cover, *images]:
            if url:
                urls.add(norm(url))

    return urls


def write_report(results) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Media URL check report", "status\tcontent_type\turl"]
    for url, status, content_type in results:
        lines.append(f"{status}\t{content_type}\t{url}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(results, *, quiet: bool) -> None:
    issues: list[tuple[str, str, str]] = []
    for url, status, content_type in results:
        content = str(content_type or "")
        if status != 200 or not content.startswith("image/"):
            issues.append((str(status), content, url))

    total = len(results)
    if issues:
        print(f"WARN media urls: {len(issues)} (see {REPORT_PATH})")
        if not quiet:
            for status, content_type, url in issues[:50]:
                print(status, content_type, url)
    else:
        print(f"All media urls OK: {total}")


async def run(quiet: bool) -> None:
    urls = await collect_urls()
    results = await asyncio.gather(*[head(url) for url in urls])
    write_report(results)
    summarize(results, quiet=quiet)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check external media URLs via HTTP HEAD requests")
    parser.add_argument("--quiet", action="store_true", help="suppress per-URL warnings; print only summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    asyncio.run(run(args.quiet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
