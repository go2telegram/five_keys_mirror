"""Administrative tooling for the multi-agent collaboration module."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from agents.runtime import get_network, is_enabled

router = Router()


def _format_ts(timestamp: Optional[float]) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _escape(text: Optional[str]) -> str:
    return html.escape(text or "")


@router.message(Command("agents"))
async def agents_admin(m: Message) -> None:
    if m.from_user.id != settings.ADMIN_ID:
        return

    if not is_enabled():
        await m.answer("Мультиагентный режим выключен. Установи ENABLE_MULTI_AGENT=true и перезапусти бота.")
        return

    network = get_network()
    if network is None:
        await m.answer("Сеть агентов не инициализирована.")
        return

    text = m.text or ""
    payload = text.split(maxsplit=1)
    if len(payload) == 1:
        await _send_status(m, network)
        return

    rest = payload[1].strip()
    if not rest or rest.lower() == "status":
        await _send_status(m, network)
        return

    if rest.lower() in {"help", "-h", "--help"}:
        await _send_help(m)
        return

    command_word, _, remainder = rest.partition(" ")
    command_word = command_word.lower()

    if command_word == "broadcast":
        query = remainder.strip()
        if not query:
            await m.answer("Использование: /agents broadcast <текст задачи>")
            return
        if (query.startswith('"') and query.endswith('"')) or (query.startswith("'") and query.endswith("'")):
            query = query[1:-1]
        await _handle_broadcast(m, network, query)
        return

    await m.answer("Неизвестная подкоманда. Используй /agents help для справки.")


async def _handle_broadcast(message: Message, network, query: str) -> None:
    note = await message.answer(f"📡 Рассылаю задачу: <b>{_escape(query)}</b>")
    task_id: Optional[str] = None
    try:
        task_id, consensus = await network.dispatch_task(query, context={"title": query, "prompt": query})
    except asyncio.TimeoutError:
        await message.answer("⚠️ Таймаут ожидания консенсуса.")
        return
    except RuntimeError as exc:
        await message.answer(f"⚠️ Не удалось получить консенсус: {exc}")
        return
    finally:
        try:
            if task_id:
                await note.edit_text(f"📡 Задача отправлена: <code>{task_id[:8]}</code>")
            else:
                await note.delete()
        except Exception:
            pass

    record = network.get_task(task_id)
    responses_block = ""
    if record and record.responses:
        lines = [f"• <b>{_escape(agent)}</b>: {_escape(resp)}" for agent, resp in sorted(record.responses.items())]
        responses_block = "\n" + "\n".join(lines)

    consensus_text = _escape(consensus)
    await message.answer(
        "✅ Консенсус достигнут\n"
        f"<b>Задача:</b> <code>{task_id[:8]}</code>\n"
        f"<pre>{consensus_text}</pre>"
        f"{responses_block}"
    )


async def _send_status(message: Message, network) -> None:
    peers = network.peers_snapshot()
    tasks = network.list_tasks(limit=5)

    lines = ["🤖 <b>Соседи</b>:"]
    if not peers:
        lines.append("• не настроены")
    else:
        for peer in peers:
            icon = "🟢" if peer["healthy"] else "🔴"
            line = f"{icon} <b>{_escape(peer['id'])}</b> → {_escape(peer['endpoint'])}"
            if peer["last_seen"]:
                line += f" (посл. {_format_ts(peer['last_seen'])})"
            if peer["last_error"]:
                line += f" — <i>{_escape(peer['last_error'])}</i>"
            lines.append(line)

    lines.append("\n🗂 <b>Последние задачи</b>:")
    if not tasks:
        lines.append("• пока нет")
    else:
        for record in tasks:
            icon = "✅" if record.status == "consensus" else "⏳"
            preview = record.result or record.task
            preview = preview.replace("\n", " ")
            if len(preview) > 90:
                preview = preview[:87] + "…"
            lines.append(f"{icon} <code>{record.task_id[:8]}</code> — {_escape(preview)}")

    lines.append("\n/agents broadcast <текст> — отправить задачу всем соседям")
    await message.answer("\n".join(lines))


async def _send_help(message: Message) -> None:
    await message.answer(
        "Справка по /agents:\n"
        "• /agents — показать соседей и последние задачи\n"
        "• /agents broadcast <текст> — отправить задачу всем ботам и дождаться консенсуса"
    )
