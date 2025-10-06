"""Admin commands that control external integrations."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.storage import get_leads_all
from integrations import IntegrationManager

logger = logging.getLogger(__name__)

router = Router(name="admin-integrations")
manager = IntegrationManager.from_settings(settings)

_CONNECTOR_ALIASES = {
    "google": "google_sheets",
    "gs": "google_sheets",
    "gsheets": "google_sheets",
    "google_sheets": "google_sheets",
    "notion": "notion",
    "webhook": "webhook_sink",
    "sink": "webhook_sink",
}
_SUPPORTED_DATASETS = {"leads"}


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.ADMIN_ID)


def _resolve_connector(name: str) -> str:
    return _CONNECTOR_ALIASES.get(name.lower(), name.lower())


@router.message(Command("integrations"))
async def integrations_status(message: Message) -> None:
    if not _is_admin(message):
        return

    if not settings.ENABLE_EXTERNAL_INTEGRATIONS:
        await message.answer("Внешние интеграции отключены. Включи ENABLE_EXTERNAL_INTEGRATIONS в .env")
        return

    enabled = manager.list_enabled()
    if not enabled:
        await message.answer("Активных коннекторов нет. Проверь переменные окружения.")
        return

    lines = ["⚙️ Доступные интеграции:"]
    for slug in sorted(enabled):
        lines.append(f"• {slug}")
    lines.append("\n/export leads <connector> — экспортировать лиды")
    lines.append("Пример: /export leads google")
    await message.answer("\n".join(lines))


@router.message(Command("export"))
async def export_command(message: Message) -> None:
    if not _is_admin(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: /export <dataset> [connector] [аргументы]")
        return

    dataset = parts[1].lower()
    if dataset not in _SUPPORTED_DATASETS:
        await message.answer("Поддерживаем только экспорт лидов: /export leads [connector]")
        return

    connector_name = parts[2] if len(parts) > 2 else "google"
    connector_slug = _resolve_connector(connector_name)

    if connector_slug == "google_sheets":
        extra_title = " ".join(parts[3:]).strip()
        await _export_leads(message, connector_slug, title=extra_title or None)
    elif connector_slug == "notion":
        if len(parts) < 4:
            await message.answer("Укажи идентификатор базы Notion: /export leads notion <database_id>")
            return
        await _export_leads(message, connector_slug, database_id=parts[3])
    elif connector_slug == "webhook_sink":
        url = parts[3] if len(parts) > 3 else None
        await _export_leads(message, connector_slug, url=url)
    else:
        await message.answer(f"Неизвестный коннектор '{connector_name}'")


async def _export_leads(message: Message, connector_slug: str, **kwargs) -> None:
    leads = list(get_leads_all())
    if not leads:
        await message.answer("Лидов нет — экспорт отменен")
        return

    if not settings.ENABLE_EXTERNAL_INTEGRATIONS:
        await message.answer("Интеграции выключены. Включи ENABLE_EXTERNAL_INTEGRATIONS в .env")
        return

    try:
        result = await manager.export(connector_slug, "leads", leads, **kwargs)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unexpected error during export")
        await message.answer("Во время экспорта произошла ошибка. Подробности в логах.")
        return

    if result.ok:
        suffix = f" → {result.url}" if result.url else ""
        await message.answer(f"Готово! {result.message}{suffix}")
    else:
        await message.answer(f"Не удалось экспортировать: {result.message}")
