from __future__ import annotations

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.quiz.engine import (
    QuizDefinition,
    QuizHooks,
    QuizResultContext,
    register_quiz_hooks,
    start_quiz,
)
from app.reco import product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import commit_safely, set_last_plan

from .quiz_common import send_product_cards

router = Router()


def _register_hooks() -> None:
    register_quiz_hooks("sleep", QuizHooks(on_finish=_on_finish_sleep))


def _sleep_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 9:
        return (
            "mild",
            "Сон в балансе",
            "sleep_ok",
            ["OMEGA3", "D3"],
        )
    if total <= 13:
        return (
            "moderate",
            "Нужна мягкая поддержка",
            "sleep_mild",
            ["MAG_B6", "OMEGA3"],
        )
    return (
        "severe",
        "Сон сильно просел",
        "sleep_high",
        ["MAG_B6", "OMEGA3", "D3"],
    )


async def _on_finish_sleep(
    call: CallbackQuery, definition: QuizDefinition, result: QuizResultContext
) -> bool:
    level_key, level_label, ctx, rec_codes = _sleep_outcome(result.total_score)
    lines = product_lines(rec_codes[:3], ctx)

    actions = [
        "Экран-детокс за 60 минут до сна и мягкий свет.",
        "Фиксируй время отбоя и подъёма в пределах ±30 минут.",
        "10 минут утреннего света и короткая прогулка днём.",
        "Лёгкий ужин за 3 часа до сна, кофеин — не позже 14:00.",
    ]
    notes = "Для расслабления — дыхание 4–7–8, тёплый душ и проветривание спальни."

    plan_payload = {
        "title": "План: Сон",
        "context": "sleep",
        "context_name": "Сон",
        "level": level_label,
        "products": rec_codes[:3],
        "lines": lines,
        "actions": actions,
        "notes": notes,
        "order_url": settings.velavie_url,
    }

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, call.from_user.id, call.from_user.username)
        await set_last_plan(session, call.from_user.id, plan_payload)
        await events_repo.log(
            session,
            call.from_user.id,
            "quiz_finish",
            {"quiz": "sleep", "score": result.total_score, "level": level_label},
        )
        await commit_safely(session)

    summary_tags = sorted(set(result.threshold.tags) | set(result.collected_tags))
    tag_line = " ".join(f"#{tag}" for tag in summary_tags)
    message = call.message
    if message:
        parts = [
            f"🛌 <b>Тест «{definition.title}»</b> завершён!",
            f"Сумма баллов: <b>{result.total_score}</b>",
            f"Результат: <b>{result.threshold.label}</b>",
            result.threshold.advice,
        ]
        if tag_line:
            parts.append("")
            parts.append(tag_line)
        await message.answer("\n".join(part for part in parts if part).strip())

    cards = pick_for_context("sleep", level_key, rec_codes[:3])
    await send_product_cards(
        call,
        f"Итог: {level_label}",
        cards,
        bullets=actions,
        headline=notes,
        back_cb="quiz:menu",
    )

    return True


@router.callback_query(F.data == "quiz:sleep")
async def quiz_sleep_start(call: CallbackQuery, state: FSMContext) -> None:
    await start_quiz(call, state, "sleep")


_register_hooks()
