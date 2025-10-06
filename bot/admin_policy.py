"""Admin utilities for inspecting and steering the meta-policy AI."""
from __future__ import annotations

from typing import Dict

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from policy import get_policy_engine

router = Router()
_engine = get_policy_engine()
_engine.set_enabled(settings.ENABLE_META_POLICY_AI)


def _format_policy_status(status: Dict[str, object]) -> str:
    header = ["🤖 <b>Meta policy AI</b>"]
    header.append("Статус: включён ✅" if status.get("enabled") else "Статус: выключен ⛔")

    metrics = status.get("metrics") or {}
    if metrics:
        metrics_lines = ["<b>Метрики</b>"]
        for key, value in metrics.items():
            metrics_lines.append(f"• {key}: {value}")
        header.append("\n".join(metrics_lines))

    policies = status.get("policies") or []
    if policies:
        policy_lines = ["<b>Текущие политики</b>"]
        for idx, policy in enumerate(policies, 1):
            policy_lines.append(
                "{idx}. {title} — {directive} (приоритет: {priority}, статус: {status})\n↳ {rationale}".format(
                    idx=idx,
                    title=policy.get("title", "(без названия)"),
                    directive=policy.get("directive", ""),
                    priority=policy.get("priority", ""),
                    status=policy.get("status", ""),
                    rationale=policy.get("rationale", ""),
                )
            )
        header.append("\n".join(policy_lines))
    else:
        header.append("Активных ограничений нет — действует базовый режим.")

    rationales = status.get("rationales") or []
    if rationales:
        header.append("<b>Обоснования</b>:\n" + "\n".join(f"• {item}" for item in rationales))

    return "\n\n".join(header)


@router.message(Command("policy_status"))
async def policy_status(message: Message) -> None:
    """Show current policy status for admins."""

    if message.from_user.id != settings.ADMIN_ID:
        return

    if not settings.ENABLE_META_POLICY_AI:
        await message.answer("Meta policy AI отключён. Установите ENABLE_META_POLICY_AI=true для активации.")
        return

    status = _engine.get_status()
    await message.answer(_format_policy_status(status))


@router.message(Command("policy_history"))
async def policy_history(message: Message) -> None:
    """Return the latest policy history entries."""

    if message.from_user.id != settings.ADMIN_ID:
        return

    history = _engine.get_history(limit=10)
    if not history:
        await message.answer("История ещё не сформирована.")
        return

    chunks = []
    for item in reversed(history):
        ts = item.get("ts", "")
        rationales = "\n".join(f"• {r}" for r in item.get("rationales", []))
        policies = item.get("policies", [])
        if policies:
            policies_repr = "\n".join(
                f"  - {p.get('title','')} ({p.get('directive','')}, приоритет: {p.get('priority','')})"
                for p in policies
            )
        else:
            policies_repr = "  - (без активных правил)"
        chunks.append(f"<b>{ts}</b>\n{policies_repr}\n{rationales}")

    await message.answer("\n\n".join(chunks))


@router.message(Command("policy_simulate"))
async def policy_simulate(message: Message) -> None:
    """Allow admins to inject metrics for simulation purposes."""

    if message.from_user.id != settings.ADMIN_ID:
        return

    if not settings.ENABLE_META_POLICY_AI:
        await message.answer("Meta policy AI отключён, симуляция невозможна.")
        return

    parts = message.text.split()
    metrics: Dict[str, float] = {}
    for raw in parts[1:]:
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        try:
            metrics[key] = float(value)
        except ValueError:
            continue

    if not metrics:
        await message.answer("Использование: /policy_simulate error_rate=0.32 response_latency=5.5")
        return

    status = _engine.update_metrics(metrics, source="telegram-admin")
    await message.answer(
        "Метрики обновлены:\n" + "\n".join(f"• {k} = {v}" for k, v in metrics.items()) + "\n\n" + _format_policy_status(status)
    )
