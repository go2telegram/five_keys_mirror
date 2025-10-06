"""Админские инструменты для контроля межсетевой дипломатии."""
from __future__ import annotations

from typing import Dict

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from diplomacy.handshake import DiplomacyHandshake, DiplomacyError, StrategyReport


router = Router()


STRATEGY_TITLES: Dict[str, str] = {
    "knowledge_exchange": "Обмен знаниями",
    "trade_agreement": "Торговые контракты",
    "alert_sharing": "Обмен алертами",
}


@router.message(Command("diplomacy_status"))
async def diplomacy_status(message: Message):
    """Показать состояние обменов между сетями."""
    if message.from_user.id != settings.ADMIN_ID:
        return

    if not settings.ENABLE_INTER_NETWORK_DIPLOMACY:
        await message.answer(
            "⚠️ Интерсетевая дипломатия выключена. Установите "
            "ENABLE_INTER_NETWORK_DIPLOMACY=true, чтобы активировать обмены."
        )
        return

    handshake = DiplomacyHandshake()
    try:
        report = handshake.perform_handshake()
    except DiplomacyError as exc:
        await message.answer(
            "❌ Не удалось выполнить дипломатическое рукопожатие.\n"
            f"Причина: {exc}"
        )
        return

    lines = [
        "🤝 <b>Интерсетевая дипломатия</b>",
        f"Связь: {report.context.get('primary_title')} ↔ {report.context.get('counterpart_title')}",
        f"Отчёт: {report.timestamp}",
        "",
    ]

    status_word = "успешно" if report.concluded else "требует внимания"
    lines.append(f"Итог: {status_word}.")

    for strategy in report.strategies:
        lines.extend(_render_strategy(strategy))

    await message.answer("\n".join(lines))


def _render_strategy(strategy: StrategyReport) -> list[str]:
    title = STRATEGY_TITLES.get(strategy.name, strategy.name)
    emoji = {
        "ok": "✅",
        "skipped": "⏭️",
        "deferred": "⏳",
    }.get(strategy.status, "ℹ️")

    block = [
        "",
        f"{emoji} <b>{title}</b>",
        strategy.summary,
    ]

    if strategy.name == "knowledge_exchange":
        shared = strategy.payload.get("shared_topics", [])
        new_primary = strategy.payload.get("new_for_primary", [])
        new_counter = strategy.payload.get("new_for_counterpart", [])
        if shared:
            block.append("Общий пул: " + ", ".join(shared[:5]))
            if len(shared) > 5:
                block.append(f"…и ещё {len(shared) - 5} тем")
        block.append(
            "Передано ядру: " + (", ".join(new_primary) if new_primary else "— обновлений нет")
        )
        block.append(
            "Передано партнёру: "
            + (", ".join(new_counter) if new_counter else "— обновлений нет")
        )

    if strategy.name == "trade_agreement":
        outbound = strategy.payload.get("outbound_contracts", [])
        inbound = strategy.payload.get("inbound_contracts", [])
        balance = strategy.payload.get("balance", 0)
        if outbound:
            goods = ", ".join(f"{item['good']} ({item['volume']})" for item in outbound)
            block.append(f"Экспортируем: {goods}")
        if inbound:
            goods = ", ".join(f"{item['good']} ({item['volume']})" for item in inbound)
            block.append(f"Импортируем: {goods}")
        block.append(f"Баланс обмена: {'+' if balance >= 0 else ''}{balance}")

    if strategy.name == "alert_sharing":
        forwarded = strategy.payload.get("forwarded", [])
        received = strategy.payload.get("received", [])
        if forwarded:
            block.append("Наши алерты: " + "; ".join(forwarded))
        if received:
            block.append("Алерты партнёра: " + "; ".join(received))

    return block


__all__ = ["router", "diplomacy_status"]
