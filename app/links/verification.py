"""Asynchronous HEAD checks for imported links."""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

import aiohttp
from aiogram import Bot

from app.background import background_queue
from .importer import LinkRecord

_CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)


async def _check_url(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url, allow_redirects=True) as response:
            if response.status < 400:
                return True
            if response.status == 405:
                async with session.get(url, allow_redirects=True) as get_resp:
                    return get_resp.status < 400
    except Exception:
        return False
    return False


async def verify_links(
    bot: Bot,
    chat_id: int,
    entries: Sequence[LinkRecord],
    *,
    session_factory=aiohttp.ClientSession,
) -> None:
    """Perform HEAD checks and send a summary message."""

    if not entries:
        return

    unreachable: list[LinkRecord] = []
    async with session_factory(timeout=_CLIENT_TIMEOUT) as session:
        for record in entries:
            ok = await _check_url(session, record.url)
            if not ok:
                unreachable.append(record)

    if not unreachable:
        text = "✅ Проверка ссылок завершена: все URL отвечают на HEAD-запросы."
    else:
        lines = ["⚠️ Проверка ссылок завершена: часть URL недоступна:"]
        for record in unreachable:
            label = record.id or record.type
            lines.append(f"• {label}: {record.url}")
        text = "\n".join(lines)
    await bot.send_message(chat_id, text)


def schedule_verification(bot: Bot, chat_id: int, entries: Iterable[LinkRecord]) -> None:
    """Schedule link verification in the background queue or run inline."""

    payload = [LinkRecord(type=item.type, id=item.id, url=item.url) for item in entries]

    async def job() -> None:
        await verify_links(bot, chat_id, payload)

    if not background_queue.submit(job):
        asyncio.create_task(job())


__all__ = ["schedule_verification", "verify_links"]
