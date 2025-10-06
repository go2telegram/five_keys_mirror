"""Jobs responsible for catalog health checks."""
from __future__ import annotations

from typing import List, Tuple

import httpx
from aiogram import Bot

from app.catalog import BUY_URLS, PRODUCTS
from app.config import settings


async def _check_url(client: httpx.AsyncClient, url: str) -> Tuple[bool, int | None, str | None]:
    try:
        response = await client.get(url, timeout=25.0)
        if response.status_code >= 400:
            return False, response.status_code, None
        return True, response.status_code, None
    except httpx.HTTPError as exc:
        return False, None, str(exc)


async def _collect_broken_links() -> List[str]:
    proxies = settings.HTTP_PROXY_URL or None
    broken: List[str] = []
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=25.0,
        headers={"User-Agent": "CatalogBot/1.0"},
        trust_env=False,
        proxies=proxies,
    ) as client:
        for code, product in PRODUCTS.items():
            title = product.get("title", code)
            for label, url in (
                ("image", product.get("image_url")),
                ("buy", BUY_URLS.get(code)),
            ):
                if not url:
                    continue
                ok, status, error = await _check_url(client, url)
                if ok:
                    continue
                reason = f"HTTP {status}" if status else (error or "no response")
                broken.append(f"• {title} ({code}) — {label}: {reason}\n  {url}")
    return broken


async def run_catalog_link_check(bot: Bot, chat_id: int | None = None) -> str:
    broken = await _collect_broken_links()
    if broken:
        lines = ["⚠️ Проверка каталога: найдены проблемные ссылки."] + broken
    else:
        lines = [
            "✅ Проверка каталога: ошибок не найдено.",
            f"Всего товаров: {len(PRODUCTS)}",
        ]
    text = "\n".join(lines)
    if chat_id:
        try:
            await bot.send_message(chat_id, text, disable_web_page_preview=True)
        except Exception:
            pass
    return text
