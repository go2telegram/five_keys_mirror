"""Handlers that expose the internal economy to Telegram users."""
from __future__ import annotations

import datetime as dt

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.storage import save_event
from economy import service
from economy.models import Transaction

router = Router()


def _format_ts(ts: dt.datetime) -> str:
    return ts.strftime("%d.%m %H:%M")


def _format_transaction(tx: Transaction) -> str:
    icon = ""  # default fallback
    direction = ""
    if tx.kind == "earn":
        icon = "⬆️"
        direction = "зачисление"
    elif tx.kind == "spend":
        icon = "⬇️"
        direction = "списание"
    elif tx.kind == "transfer_in":
        icon = "⬅️"
        direction = f"перевод от {tx.actor_id}"
    elif tx.kind == "transfer_out":
        icon = "➡️"
        direction = f"перевод {tx.counterparty_id}"
    else:
        direction = tx.kind

    note = f" — {tx.note}" if tx.note else ""
    return f"{icon} {_format_ts(tx.ts)} • {direction}: <b>{tx.amount}</b>{note}"


@router.message(Command("wallet"))
async def show_wallet(message: Message):
    if not settings.ENABLE_GLOBAL_ECONOMY:
        await message.answer("Экономика пока выключена. Попробуйте позже.")
        return

    wallet = service.get_wallet(message.from_user.id)
    history = service.get_wallet_history(message.from_user.id, limit=5)

    header = (
        "💰 <b>Ваш кошелёк</b>\n"
        f"Баланс: <b>{wallet.balance}</b> токенов\n"
        f"Уровень: <b>{wallet.level}</b>\n"
        f"Начислено: {wallet.tokens_earned}\n"
        f"Потрачено: {wallet.tokens_spent}"
    )

    lines = [header]
    if history:
        lines.append("\n<b>Последние операции</b>")
        lines.extend(_format_transaction(tx) for tx in history)
    else:
        lines.append("\nОперации пока не проводились — заработайте первые токены!")

    save_event(message.from_user.id, None, "wallet_view")
    await message.answer("\n".join(lines))


@router.message(Command("transfer"))
async def transfer_tokens(message: Message):
    if not settings.ENABLE_GLOBAL_ECONOMY:
        await message.answer("Экономика пока выключена. Попробуйте позже.")
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Использование: /transfer <user_id> <amount>")
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("ID и сумма должны быть числами. Пример: /transfer 123456789 50")
        return

    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return

    try:
        service.transfer_tokens(message.from_user.id, target_id, amount)
    except ValueError as exc:
        await message.answer(f"⚠️ Не удалось выполнить перевод: {exc}")
        return

    wallet = service.get_wallet(message.from_user.id)
    save_event(message.from_user.id, None, "wallet_transfer", {"to": target_id, "amount": amount})

    await message.answer(
        "✅ Перевод выполнен!\n"
        f"Отправлено: <b>{amount}</b> токенов пользователю <b>{target_id}</b>.\n"
        f"Текущий баланс: <b>{wallet.balance}</b>"
    )
