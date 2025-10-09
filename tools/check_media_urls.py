import asyncio
import glob
import json
import os
import sys

import aiohttp
import yaml


async def head(url: str):
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as response:
                return url, response.status, response.headers.get("Content-Type", "")
    except Exception as exc:  # noqa: BLE001 - we only log the exception message
        return url, -1, str(exc)


async def collect_urls():
    urls = set()

    data = json.load(open("app/catalog/products.json", encoding="utf-8"))
    items = data["products"] if isinstance(data, dict) else data
    for product in items:
        image = product.get("image") or (product.get("images") or [None])[0]
        if image and image.startswith("http"):
            urls.add(image)

    for path in glob.glob("app/quiz/data/*.yaml"):
        with open(path, encoding="utf-8") as handle:
            yml = yaml.safe_load(handle)

        base = os.getenv("QUIZ_IMG_BASE", "")

        def norm(url: str):
            return url if url.startswith("http") else f"{base.rstrip('/')}/{url.lstrip('/')}"

        cover = yml.get("cover")
        images = [question.get("image") for question in yml.get("questions", [])]

        for url in [cover, *images]:
            if url:
                urls.add(norm(url))

    return urls


async def _check_partner_links() -> int:
    try:
        from app.services.partner_links import (
            check_partner_links,
            filter_partner_issues,
        )
    except Exception as exc:  # pragma: no cover - optional runtime import
        print(f"WARN failed to import partner link checker: {exc}")
        return 1

    results = await check_partner_links()
    issues = filter_partner_issues(results)

    if not results:
        print("No partner order links discovered in catalog.")
        return 0

    if issues:
        print(f"WARN partner order links: {len(issues)} issues (checked {len(results)})")
        for issue in issues[:20]:
            parts = []
            if issue.error:
                parts.append(issue.error)
            if issue.status < 200 or issue.status >= 400:
                parts.append(f"status={issue.status}")
            if issue.utm_issues:
                parts.extend(issue.utm_issues)
            detail = "; ".join(parts) or "неизвестная ошибка"
            print(f"{issue.link.product_id}: {detail}\n  {issue.link.url}")
            if issue.final_url and issue.final_url != issue.link.url:
                print(f"  → {issue.final_url}")
        if len(issues) > 20:
            print(f"… truncated {len(issues) - 20} more issues")
        return 1

    print(f"All partner order links OK: {len(results)}")
    return 0


async def main() -> int:
    urls = await collect_urls()
    results = await asyncio.gather(*[head(url) for url in urls])
    bad = [result for result in results if result[1] != 200 or not str(result[2]).startswith("image/")]

    exit_code = 0
    if bad:
        exit_code = 1
        print("WARN media urls:", len(bad))
        for url, status, content_type in bad[:50]:
            print(status, content_type, url)
    else:
        print("All media urls OK:", len(results))

    partner_exit = await _check_partner_links()
    exit_code = exit_code or partner_exit
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
