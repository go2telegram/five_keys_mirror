from __future__ import annotations

from typing import Callable

import streamlit as st


DecisionCallback = Callable[[str, str, str | None], None]

STATUS_LABELS = {
    "pending": "Ожидает решения",
    "accepted": "Принята",
    "modified": "Изменена",
    "rejected": "Отклонена",
}


def render_task_panel(task: dict[str, str], *, operator_name: str, on_decision: DecisionCallback) -> None:
    """Render a single collaboration card with decision buttons."""

    with st.container(border=True):
        st.subheader(task["title"], anchor=False)
        status = task.get("status", "pending")
        status_text = STATUS_LABELS.get(status, status)
        st.caption(f"ID: {task['id']} · Статус: {status_text}")
        st.write(task.get("description", ""))

        with st.expander("Авто-решение", expanded=False):
            st.code(task.get("auto_solution", ""))

        recommendation = st.text_area(
            "Рекомендация для клиента",
            value=task.get("recommendation", ""),
            key=f"rec-{task['id']}",
            height=160,
        )
        notes = st.text_area(
            "Заметки оператора (опционально)",
            value=task.get("operator_notes", ""),
            key=f"notes-{task['id']}",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            accept = st.button("Принять", key=f"accept-{task['id']}")
        with col2:
            modify = st.button("Изменить", key=f"modify-{task['id']}")
        with col3:
            reject = st.button("Отклонить", type="primary", key=f"reject-{task['id']}")

        if accept:
            _handle_decision(
                "accepted",
                operator_name,
                recommendation,
                notes,
                on_decision,
            )
        elif modify:
            _handle_decision(
                "modified",
                operator_name,
                recommendation,
                notes,
                on_decision,
            )
        elif reject:
            _handle_decision(
                "rejected",
                operator_name,
                recommendation,
                notes,
                on_decision,
            )


def _handle_decision(
    status: str,
    operator_name: str,
    recommendation: str,
    notes: str,
    callback: DecisionCallback,
) -> None:
    if not operator_name.strip():
        st.error("Укажите имя оператора слева, чтобы сохранить решение.")
        return

    callback(status, recommendation, notes or None)
    st.success("Решение сохранено")
    st.experimental_rerun()
