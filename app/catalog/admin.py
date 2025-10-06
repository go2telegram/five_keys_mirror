"""Admin commands for catalog maintenance and analytics."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.catalog import PRODUCTS, get_stats, reload_catalog
from app.config import settings
from jobs.catalog_checks import run_catalog_link_check

router = Router()


def _is_enabled() -> bool:
    return getattr(settings, "ENABLE_CATALOG_ADMIN", True)


def _admin_ids() -> set[int]:
    ids = {settings.ADMIN_ID}
    extra = getattr(settings, "ADMIN_IDS", None)
    if extra:
        for raw in str(extra).split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ids.add(int(raw))
            except ValueError:
                continue
    return ids


def _is_authorized(message: Message) -> bool:
    if not _is_enabled():
        return False
    if not message.from_user:
        return False
    return message.from_user.id in _admin_ids()


def _format_counter(counter, mapper, limit: int = 5) -> str:
    if not counter:
        return "—"
    parts = []
    for idx, (key, value) in enumerate(counter.most_common(limit), start=1):
        parts.append(f"{idx}. {mapper(key)} — {value}")
    return "\n".join(parts)


@router.message(Command("catalog_reload"))
async def catalog_reload_cmd(message: Message) -> None:
    if not _is_authorized(message):
        return
    try:
        path, count = reload_catalog()
    except Exception as exc:  # pragma: no cover - defensive, reported to admin
        await message.answer(f"⚠️ Ошибка при загрузке каталога: {exc}")
        return
    await message.answer(
        "Каталог обновлён.\n"
        f"Файл: <code>{path}</code>\n"
        f"Позиции: {count}"
    )


@router.message(Command("catalog_stats"))
async def catalog_stats_cmd(message: Message) -> None:
    if not _is_authorized(message):
        return
    stats = get_stats()

    def product_name(code: str) -> str:
        return PRODUCTS.get(code, {}).get("title", code)

    report_lines = ["📈 Каталог: статистика"]
    for period, label in (("day", "За 24 часа"), ("week", "За 7 дней")):
        data = stats.get(period, {})
        report_lines.append(f"\n<b>{label}</b>")
        report_lines.append("Товары — просмотры:")
        report_lines.append(_format_counter(data.get("product_views"), product_name))
        report_lines.append("Товары — клики:")
        report_lines.append(_format_counter(data.get("product_clicks"), product_name))
        report_lines.append("Категории — просмотры:")
        report_lines.append(_format_counter(data.get("category_views"), str))
        report_lines.append("Категории — клики:")
        report_lines.append(_format_counter(data.get("category_clicks"), str))
    await message.answer("\n".join(report_lines))


@router.message(Command("catalog_broken"))
async def catalog_broken_cmd(message: Message) -> None:
    if not _is_authorized(message):
        return
    await message.answer("⏳ Проверяю ссылки…")
    await run_catalog_link_check(message.bot, message.chat.id)


__all__ = ["router"]
