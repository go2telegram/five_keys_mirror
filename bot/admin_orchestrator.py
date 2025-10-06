"""Admin utilities for interacting with the meta orchestrator inside Telegram."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from orchestrator.manager import orchestrator_manager

router = Router()


def _format_agent(agent: Dict[str, object]) -> str:
    tasks: List[Dict[str, object]] = agent.get("assigned_tasks", [])  # type: ignore[assignment]
    utilisation = float(agent.get("utilisation", 0))
    lines = [
        "🤖 <b>{agent}</b> — pri={pri} cap={cap} util={util}".format(
            agent=agent.get("agent_id"),
            pri=agent.get("priority"),
            cap=agent.get("capacity"),
            util=f"{utilisation:.0%}",
        )
    ]
    if not agent.get("active", True):
        lines.append("   ⚠️ агент отключён")
    if tasks:
        for task in tasks:
            started = datetime.fromtimestamp(task["assigned_at"]).strftime("%H:%M:%S")
            in_progress = float(task.get("in_progress_for", 0))
            total_latency = float(task.get("total_latency", 0))
            lines.append(
                "   • {task_id} (p={priority}, in={in_prog:.2f}s, lat={lat:.2f}s) payload={payload} started={started}".format(
                    task_id=task.get("task_id"),
                    priority=task.get("priority"),
                    in_prog=in_progress,
                    lat=total_latency,
                    payload=task.get("payload"),
                    started=started,
                )
            )
    else:
        lines.append("   • свободен")
    return "\n".join(lines)


@router.message(Command("orchestrator"))
async def show_orchestrator(message: Message) -> None:
    """Send orchestrator status to the admin chat."""

    if message.from_user is None or message.from_user.id != settings.ADMIN_ID:
        return

    if not settings.ENABLE_META_ORCHESTRATOR:
        await message.answer("🧠 Мета-оркестратор выключен (ENABLE_META_ORCHESTRATOR=false).")
        return

    snapshot = await orchestrator_manager.get_status_snapshot()
    agents = snapshot.get("agents", [])
    pending = snapshot.get("pending_tasks", [])
    metrics = snapshot.get("metrics", {})

    if not agents and not pending:
        await message.answer("🧠 Оркестратор включён, но пока нет агентов и задач.")
        return

    parts: List[str] = ["🧠 <b>Мета-оркестратор</b>"]

    if agents:
        parts.append("\n".join(_format_agent(agent) for agent in agents))

    if pending:
        pending_lines = ["🕒 Ожидают очереди:"]
        for task in pending:
            queued_at = datetime.fromtimestamp(task["created_at"]).strftime("%H:%M:%S")
            pending_lines.append(
                "   • "
                f"{task['task_id']} (p={task['priority']}, queued={queued_at}, payload={task['payload']})"
            )
        parts.append("\n".join(pending_lines))

    if metrics:
        parts.append(
            "📈 Метрики:\n"
            f"• tasks_distributed_total: {metrics.get('tasks_distributed_total', 0)}\n"
            f"• avg_task_latency: {metrics.get('avg_task_latency', 0):.3f}s"
        )

    await message.answer("\n\n".join(parts))
