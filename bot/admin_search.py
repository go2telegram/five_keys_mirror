import time
from typing import Sequence

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.storage import save_event
from knowledge.search import SearchResult, get_search_service

router = Router()


def _format_results(results: Sequence[SearchResult]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(results, 1):
        score_pct = max(0.0, min(1.0, item.score)) * 100
        lines.append(
            f"{idx}. <b>{item.title}</b> — {item.snippet}\n"
            f"<code>{item.path}</code> · {item.source} · {score_pct:.0f}%"
        )
    return "\n\n".join(lines)


@router.message(Command("search"))
async def admin_search(message: Message) -> None:
    if message.from_user.id != settings.ADMIN_ID:
        return
    if not settings.ENABLE_SEMANTIC_SEARCH:
        await message.answer("🔌 Семантический поиск отключён. Включите ENABLE_SEMANTIC_SEARCH.")
        return

    text = message.text or ""
    query = text.split(maxsplit=1)
    if len(query) < 2 or not query[1].strip():
        await message.answer("Использование: /search <запрос>")
        return

    payload = query[1].strip()
    service = await get_search_service()

    if payload.lower() in {"пересборка", "rebuild"}:
        await service.rebuild()
        await message.answer("🔄 Индекс пересобран.")
        return

    started = time.perf_counter()
    results = await service.search(payload)
    elapsed_ms = (time.perf_counter() - started) * 1000

    save_event(
        user_id=message.from_user.id,
        source="admin",
        action="semantic_search",
        payload={
            "query": payload,
            "results": [r.path for r in results],
            "latency_ms": round(elapsed_ms, 2),
        },
    )

    if not results:
        await message.answer(f"Ничего не найдено. ⏱ {elapsed_ms:.0f} мс")
        return

    header = f"🔎 Нашлось {len(results)} фрагмент(ов). ⏱ {elapsed_ms:.0f} мс"
    await message.answer(f"{header}\n\n{_format_results(results)}")
