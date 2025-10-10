from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable
import os
import sys

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from bot.admin_collab import (  # noqa: E402  (import after sys.path mutation)
    ensure_storage,
    load_tasks,
    update_task_decision,
)
from collab.ui import render_task_panel  # noqa: E402


STATUS_LABELS = {
    "pending": "Ожидают решения",
    "accepted": "Принятые",
    "modified": "Изменённые",
    "rejected": "Отклонённые",
}


def _filter_tasks(tasks: Iterable[dict[str, str]], status: str | None) -> list[dict[str, str]]:
    if status is None:
        return list(tasks)
    return [task for task in tasks if task.get("status", "pending") == status]


def main() -> None:
    st.set_page_config(page_title="Human-in-the-loop", layout="wide")
    ensure_storage()

    if os.getenv("ENABLE_HUMAN_COLLAB", "false").lower() not in {"1", "true", "yes"}:
        st.warning(
            "Режим совместной работы отключён. Установите переменную окружения "
            "ENABLE_HUMAN_COLLAB=true для активации интерфейса."
        )
        st.stop()

    st.title("🤝 Совместная работа оператора и ИИ")
    st.caption("Редактируйте предложения сети и фиксируйте решения.")

    if "operator_name" not in st.session_state:
        st.session_state.operator_name = ""

    with st.sidebar:
        st.header("Оператор")
        st.session_state.operator_name = st.text_input(
            "Имя", value=st.session_state.operator_name, placeholder="Например, Анна"
        )
        st.markdown(
            """
            - Выберите задачу и при необходимости отредактируйте текст рекомендации.
            - Нажмите «Принять», «Изменить» или «Отклонить», чтобы зафиксировать решение.
            - Все действия записываются в `collab_history.jsonl`.
            """
        )

    tasks = load_tasks()
    status_counter = Counter(task.get("status", "pending") for task in tasks)

    tabs = st.tabs(
        [
            "Все",
            f"{STATUS_LABELS['pending']} ({status_counter.get('pending', 0)})",
            f"{STATUS_LABELS['accepted']} ({status_counter.get('accepted', 0)})",
            f"{STATUS_LABELS['modified']} ({status_counter.get('modified', 0)})",
            f"{STATUS_LABELS['rejected']} ({status_counter.get('rejected', 0)})",
        ]
    )

    tab_keys = ["all", "pending", "accepted", "modified", "rejected"]
    for tab, status, tab_key in zip(
        tabs,
        [None, "pending", "accepted", "modified", "rejected"],
        tab_keys,
    ):
        with tab:
            _render_task_list(
                _filter_tasks(tasks, status),
                operator_name=st.session_state.operator_name,
                widget_prefix=tab_key,
            )


def _render_task_list(
    tasks: list[dict[str, str]], *, operator_name: str, widget_prefix: str
) -> None:
    if not tasks:
        st.info("Нет задач в этой категории. Попробуйте выбрать другой фильтр.")
        return

    for task in tasks:
        render_task_panel(
            task,
            operator_name=operator_name,
            on_decision=lambda status, recommendation, notes, task_id=task["id"]: update_task_decision(
                task_id,
                status=status,
                recommendation=recommendation,
                operator=operator_name or "",
                operator_notes=notes,
            ),
            widget_prefix=widget_prefix,
        )


if __name__ == "__main__":
    main()
