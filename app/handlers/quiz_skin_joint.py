"""Quiz for skin and joint wellbeing."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.reco import product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router(name="quiz_skin_joint")

QUESTIONS: list[tuple[str, list[tuple[str, int]]]] = [
    (
        "Есть ли сухость кожи или ощущение стянутости?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Появляются ли высыпания/акне при стрессе или питании?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Как часто замечаешь ломкость ногтей или волос?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Есть ли утренняя скованность в суставах/спине?",
        [("Нет", 0), ("Иногда", 1), ("Да", 2)],
    ),
    (
        "Бывают ли щелчки/хруст в суставах при движении?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Как часто потребляешь белок (мясо/рыба/бобовые/яйца)?",
        [("Каждый приём пищи", 0), ("1–2 раза в день", 1), ("Редко", 2)],
    ),
    (
        "Добавляешь ли Омега-3 или антиоксиданты в рацион?",
        [("Регулярно", 0), ("Иногда", 1), ("Пока нет", 2)],
    ),
    (
        "Есть ли хронические нагрузки (спорт, сидячая работа)?",
        [("Умеренно", 0), ("Требуют восстановления", 1), ("Часто перегруз", 2)],
    ),
    (
        "Сколько стаканов воды пьёшь в день?",
        [("6+", 0), ("3–5", 1), ("Меньше", 2)],
    ),
    (
        "Бывают ли воспаления/отеки после тренировок?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Насколько регулярно спишь 7–8 часов?",
        [("Почти всегда", 0), ("Иногда", 1), ("Редко", 2)],
    ),
]


def _keyboard(idx: int) -> InlineKeyboardMarkup:
    _, answers = QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for _, (label, value) in enumerate(answers):
        kb.button(text=label, callback_data=f"q:skin_joint:{idx}:{value}")
    kb.button(text="⬅️ Назад", callback_data="tests:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 2)
    return kb.as_markup()


def _level(score: int) -> tuple[str, str, str]:
    if score <= 8:
        return "mild", "Кожа и суставы в норме", "skin_joint_low"
    if score <= 16:
        return "moderate", "Есть зоны для поддержки", "skin_joint_mid"
    return "severe", "Нужна системная забота", "skin_joint_high"


@router.callback_query(F.data == "quiz:skin_joint")
async def quiz_skin_joint_start(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {"quiz": "skin_joint", "idx": 0, "score": 0}
    question, _ = QUESTIONS[0]
    await safe_edit(
        c,
        f"Кожа и суставы ✨\n\nВопрос 1/{len(QUESTIONS)}:\n{question}",
        _keyboard(0),
    )


@router.callback_query(F.data.regexp(r"^q:skin_joint:\d+:\d+$"))
async def quiz_skin_joint_step(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "skin_joint":
        await c.answer()
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(QUESTIONS):
        await _finish_quiz(c)
        return

    question, _ = QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(QUESTIONS)}:\n{question}",
        _keyboard(idx),
    )


async def _finish_quiz(c: CallbackQuery) -> None:
    user_id = c.from_user.id
    sess = SESSIONS.pop(user_id, None)
    if not sess:
        await c.answer()
        return

    total = sess.get("score", 0)
    level_key, level_label, ctx = _level(total)

    rec_codes = ["ERA_MIT_UP", "OMEGA3", "T8_BLEND"]
    lines = product_lines(rec_codes, ctx)

    actions = [
        "Поддерживай белок 1.5 г/кг и витамины С+Е в рационе.",
        "Добавь суставную разминку утром и после нагрузки.",
        "Следи за водным балансом и сном не менее 7 часов.",
    ]
    notes = "Регулярно делай фото-прогресс кожи и отслеживай подвижность суставов."

    plan_payload = {
        "title": "План: кожа и суставы",
        "context": "skin_joint",
        "context_name": "Кожа и суставы",
        "level": level_label,
        "products": rec_codes,
        "lines": lines,
        "actions": actions,
        "notes": notes,
        "order_url": settings.velavie_url,
    }

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, c.from_user.username)
        await set_last_plan(session, user_id, plan_payload)
        await events_repo.log(
            session,
            user_id,
            "quiz_finish",
            {"quiz": "skin_joint", "score": total, "level": level_label},
        )
        await commit_safely(session)

    cards = pick_for_context("skin_joint", level_key, rec_codes)
    await send_product_cards(
        c,
        f"Итог: {level_label}",
        cards,
        bullets=actions,
        headline=notes,
            back_cb="tests:menu",
    )
