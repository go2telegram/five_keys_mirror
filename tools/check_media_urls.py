import asyncio
import glob
import json
import os

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


async def main():
    urls = await collect_urls()
    results = await asyncio.gather(*[head(url) for url in urls])
    bad = [result for result in results if result[1] != 200 or not str(result[2]).startswith("image/")]

    if bad:
        print("WARN media urls:", len(bad))
        for url, status, content_type in bad[:50]:
            print(status, content_type, url)
    else:
        print("All media urls OK:", len(results))


if __name__ == "__main__":
    asyncio.run(main())
