from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from sqlalchemy import select

from app.db.models import Event
from app.db.session import compat_session, session_scope
from app.repo import events as events_repo, user_profiles as user_profiles_repo
from app.storage import commit_safely
from app.utils_openai import ai_generate

SYSTEM_PROMPT_RU = (
    "Ты — wellness-эксперт. Дай структурированный лайфстайл-план без медицинских диагнозов."
    " Используй дружелюбный тон, помни что это не медицинская рекомендация."
)


async def _latest_events(
    session,
    user_id: int,
    name: str,
    limit: int,
) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.name == name)
        .order_by(Event.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


def _serialize_events(events: Iterable[Event]) -> list[Dict[str, Any]]:
    payload: list[Dict[str, Any]] = []
    for event in events:
        payload.append(
            {
                "ts": event.ts.isoformat() if event.ts else None,
                "meta": event.meta or {},
                "name": event.name,
            }
        )
    return payload


def _render_prompt(user_id: int, horizon: str, context: Dict[str, Any]) -> str:
    lines = [
        f"Пользователь: {user_id}",
        f"Период плана: {horizon}",
        "",
        "История квизов:",
    ]
    quizzes = context.get("quizzes", []) or []
    if quizzes:
        for quiz in quizzes:
            meta = quiz.get("meta", {})
            lines.append(f"• {meta.get('quiz', 'quiz')} — уровень {meta.get('level', meta.get('score'))}")
    else:
        lines.append("• нет актуальных квизов")

    lines.append("")
    lines.append("Результаты калькуляторов:")
    calcs = context.get("calculators", []) or []
    if calcs:
        for calc in calcs:
            meta = calc.get("meta", {})
            lines.append(f"• {meta.get('calc', 'calc')}: {json.dumps(meta.get('data', {}), ensure_ascii=False)}")
    else:
        lines.append("• нет свежих расчётов")

    lines.append("")
    lines.append("Последние рекомендации:")
    plans = context.get("plans", []) or []
    if plans:
        for plan in plans:
            meta = plan.get("meta", {})
            lines.append(f"• {meta.get('title') or meta.get('context_name') or 'Персональный план'}")
    else:
        lines.append("• планов пока не было")

    lines.append("")
    lines.append("Сформируй план в формате:")
    lines.append("🗓 План на <период>")
    lines.append("### Утро")
    lines.append("• ...")
    lines.append("### День")
    lines.append("• ...")
    lines.append("### Вечер")
    lines.append("• ...")
    lines.append("")
    lines.append("Фокус: питание, движение, сон, восстановление. Без лекарств и диагнозов.")
    return "\n".join(lines)


def _ensure_structure(text: str, horizon: str) -> str:
    header = f"🗓 План на {horizon}"
    result = text.strip()
    if header not in result:
        result = f"{header}\n\n{result}" if result else header
    for section in ("Утро", "День", "Вечер"):
        tag = f"### {section}"
        if tag not in result:
            result += f"\n\n{tag}\n• Выбери 1-2 простых действия для {section.lower()}."
    return result


async def build_ai_plan(user_id: int, horizon: str = "7d") -> str:
    async with compat_session(session_scope) as session:
        quizzes = await _latest_events(session, user_id, "quiz_finish", 5)
        calcs = await _latest_events(session, user_id, "calc_finish", 3)
        plans = await events_repo.recent_plans(session, user_id, limit=3)

    context = {
        "quizzes": _serialize_events(quizzes),
        "calculators": _serialize_events(calcs),
        "plans": [
            {"ts": plan.ts.isoformat() if plan.ts else None, "meta": plan.meta or {}}
            for plan in plans
        ],
    }

    prompt = _render_prompt(user_id, horizon, context)
    raw = await ai_generate(prompt, sys=SYSTEM_PROMPT_RU)
    plan_text = _ensure_structure(raw or "", horizon)

    async with compat_session(session_scope) as session:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "horizon": horizon,
            "plan_text": plan_text,
            "context": context,
        }
        await user_profiles_repo.update_plan(session, user_id, payload)
        await commit_safely(session)

    return plan_text


__all__ = ["build_ai_plan"]
