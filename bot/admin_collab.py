from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
COLLAB_DIR = REPO_ROOT / "collab"
TASKS_FILE = COLLAB_DIR / "tasks.json"
HISTORY_FILE = COLLAB_DIR / "collab_history.jsonl"


@dataclass
class CollaborationTask:
    """Represents a single AI-generated proposal that can be curated."""

    id: str
    title: str
    description: str
    recommendation: str
    auto_solution: str
    status: str = "pending"
    updated_at: str = ""
    operator: str | None = None
    operator_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data.get("updated_at"):
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CollaborationTask":
        return cls(
            id=str(raw.get("id")),
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            recommendation=raw.get("recommendation", ""),
            auto_solution=raw.get("auto_solution", ""),
            status=raw.get("status", "pending"),
            updated_at=raw.get("updated_at", ""),
            operator=raw.get("operator"),
            operator_notes=raw.get("operator_notes"),
        )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_storage() -> None:
    """Guarantee that the collaboration storage files exist."""

    COLLAB_DIR.mkdir(parents=True, exist_ok=True)

    if not TASKS_FILE.exists():
        default_tasks = [
            CollaborationTask(
                id="meal-plan-1",
                title="Еженедельный рацион",
                description=(
                    "План питания от ИИ. Проверь кол-во белка и наличие продуктов из сезонного списка."
                ),
                recommendation="Согласовать с пользователем и уточнить предпочтения по завтракам.",
                auto_solution=(
                    "1. Понедельник: овсянка на воде, куриная грудка, овощной салат.\n"
                    "2. Вторник: творог с ягодами, лосось на пару, киноа."
                ),
            ).to_dict(),
            CollaborationTask(
                id="supplement-2",
                title="Подбор добавок",
                description="ИИ рекомендовал комплекс витаминов. Проверь противопоказания.",
                recommendation="Добавить витамин D только после согласования с врачом.",
                auto_solution=(
                    "A. Омега-3 1000 мг ежедневно.\nB. Магний вечером перед сном."
                ),
            ).to_dict(),
        ]
        _write_json(TASKS_FILE, default_tasks)

    if not HISTORY_FILE.exists():
        HISTORY_FILE.touch()


def _write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        if not fp.read().strip():
            return None
        fp.seek(0)
        return json.load(fp)


def load_tasks() -> list[dict[str, Any]]:
    """Read the current list of collaboration tasks."""

    ensure_storage()
    raw = _read_json(TASKS_FILE)
    if not raw:
        return []

    tasks = [CollaborationTask.from_dict(item).to_dict() for item in raw]
    tasks.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return tasks


def save_tasks(tasks: Iterable[dict[str, Any]]) -> None:
    ensure_storage()
    _write_json(TASKS_FILE, list(tasks))


def log_history(entry: dict[str, Any]) -> None:
    ensure_storage()
    record = {"timestamp": _utcnow_iso(), **entry}
    with HISTORY_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_task_decision(
    task_id: str,
    *,
    status: str,
    recommendation: str,
    operator: str,
    operator_notes: str | None = None,
) -> dict[str, Any]:
    """Update a task with the operator decision and persist the change."""

    tasks = load_tasks()
    updated_task: dict[str, Any] | None = None

    for task in tasks:
        if task["id"] == task_id:
            previous = task.copy()
            task["status"] = status
            task["recommendation"] = recommendation
            task["operator"] = operator
            task["operator_notes"] = operator_notes or ""
            task["updated_at"] = _utcnow_iso()
            updated_task = task
            log_history(
                {
                    "action": "task_decision",
                    "task_id": task_id,
                    "status": status,
                    "operator": operator,
                    "notes": operator_notes or "",
                    "previous": previous,
                    "current": task,
                }
            )
            break

    if updated_task is None:
        raise ValueError(f"Task with id '{task_id}' was not found")

    save_tasks(tasks)
    return updated_task


def add_task(task: CollaborationTask) -> dict[str, Any]:
    tasks = load_tasks()
    if any(item["id"] == task.id for item in tasks):
        raise ValueError(f"Task with id '{task.id}' already exists")

    payload = task.to_dict()
    payload["updated_at"] = _utcnow_iso()
    tasks.append(payload)
    save_tasks(tasks)
    log_history({"action": "task_created", "task_id": task.id, "task": payload})
    return payload


__all__ = [
    "CollaborationTask",
    "ensure_storage",
    "load_tasks",
    "save_tasks",
    "update_task_decision",
    "add_task",
    "log_history",
]
