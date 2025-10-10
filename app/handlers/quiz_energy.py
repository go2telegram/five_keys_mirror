"""Energy quiz entrypoints powered by the generic quiz engine."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.links.service import get_register_url
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import send_product_cards
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
from app.utils.premium_cta import send_premium_cta

router = Router()


def _register_hooks() -> None:
    register_quiz_hooks("energy", QuizHooks(on_finish=_on_finish_energy))


def _energy_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 5:
        return (
            "mild",
            "Энергия в норме",
            "energy_norm",
            ["T8_BLEND", "OMEGA3", "VITEN"],
        )
    if total <= 10:
        return (
            "moderate",
            "Лёгкая усталость",
            "energy_light",
            ["T8_BLEND", "VITEN", "TEO_GREEN"],
        )
    return (
        "severe",
        "Выраженная усталость",
        "energy_high",
        ["T8_EXTRA", "VITEN", "MOBIO"],
    )


async def _on_finish_energy(
    user_id: int, definition: QuizDefinition, result: QuizResultContext
) -> bool:
    level_key, level_label, ctx, rec_codes = _energy_outcome(result.total_score)
    lines = product_lines(rec_codes[:3], ctx)

    actions = [
        "Ложиться до 23:00 и спать 7–9 часов.",
        "10 минут утреннего света (балкон/улица).",
        "30 минут быстрой ходьбы ежедневно.",
    ]
    notes = "Следи за гидратацией: 30–35 мл воды/кг. Ужин — за 3 часа до сна."

    plan_payload = {
        "title": "План: Энергия",
        "context": "energy",
        "context_name": "Энергия",
        "level": level_label,
        "products": rec_codes[:3],
        "lines": lines,
        "actions": actions,
        "notes": notes,
        "order_url": get_register_url(),
    }

    origin = result.origin
    username = origin.from_user.username if origin and origin.from_user else None

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, username)
        await set_last_plan(session, user_id, plan_payload)
        await events_repo.log(
            session,
            user_id,
            "quiz_finish",
            {"quiz": "energy", "score": result.total_score, "level": level_label},
        )
        await commit_safely(session)

    cards = pick_for_context("energy", level_key, rec_codes[:3])
    if origin:
        await send_product_cards(
            origin,
            f"Итог: {level_label}",
            cards,
            bullets=actions,
            headline=notes,
            back_cb="quiz:menu",
        )
        await send_premium_cta(
            origin,
            "🔓 Еженедельные обновления доступны в Премиум",
            source="quiz:energy",
        )

    return True


@router.callback_query(F.data == "quiz:energy")
async def quiz_energy_start(call: CallbackQuery, state: FSMContext) -> None:
    await start_quiz(call, state, "energy")


_register_hooks()
