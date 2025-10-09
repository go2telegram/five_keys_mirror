"""Extended stress resilience quiz."""

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
from app.utils.premium_cta import send_premium_cta

router = Router(name="quiz_stress2")

QUESTIONS: list[tuple[str, list[tuple[str, int]]]] = [
    (
        "Как часто чувствуешь эмоциональное выгорание к концу дня?",
        [("Редко", 0), ("Иногда", 1), ("Почти всегда", 2)],
    ),
    (
        "Есть ли проблемы со сном из-за мыслей или тревоги?",
        [("Нет", 0), ("Иногда", 1), ("Да", 2)],
    ),
    (
        "Как часто замечаешь скачки аппетита из-за стресса?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Удается ли уделять время прогулкам или активности на свежем воздухе?",
        [("Каждый день", 0), ("1–2 раза в неделю", 1), ("Почти нет", 2)],
    ),
    (
        "Делаешь ли дыхательные практики или расслабление (йога, медитация)?",
        [("Регулярно", 0), ("Иногда", 1), ("Пока нет", 2)],
    ),
    (
        "Как часто бывают вспышки раздражительности или слезливости?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Есть ли зажимы в плечах/шее или головные боли от напряжения?",
        [("Редко", 0), ("Иногда", 1), ("Часто", 2)],
    ),
    (
        "Сколько кофеина или стимуляторов в день?",
        [("0–1 порция", 0), ("2–3", 1), ("4+", 2)],
    ),
    (
        "Как часто берешь короткие паузы/перерывы в течение дня?",
        [("Каждый час", 0), ("2–3 раза", 1), ("Редко", 2)],
    ),
    (
        "Есть ли ощущение, что иммунитет проседает на фоне стресса?",
        [("Нет", 0), ("Иногда", 1), ("Да", 2)],
    ),
    (
        "Насколько стабильным остается настроение утром?",
        [("Стабильное", 0), ("Плавает", 1), ("Сильные перепады", 2)],
    ),
    (
        "Получается ли общаться с близкими/поддержкой регулярно?",
        [("Да", 0), ("Иногда", 1), ("Почти нет", 2)],
    ),
]


def _keyboard(idx: int) -> InlineKeyboardMarkup:
    _, answers = QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for _, (label, value) in enumerate(answers):
        kb.button(text=label, callback_data=f"q:stress2:{idx}:{value}")
    kb.button(text="⬅️ Назад", callback_data="quiz:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 2)
    return kb.as_markup()


def _level(score: int) -> tuple[str, str, str]:
    if score <= 8:
        return "mild", "Стресс под контролем", "stress_ok"
    if score <= 16:
        return "moderate", "Нужна системная разгрузка", "stress_mid"
    return "severe", "Высокий уровень стресса", "stress_high"


@router.callback_query(F.data == "quiz:stress2")
async def quiz_stress2_start(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {"quiz": "stress2", "idx": 0, "score": 0}
    question, _ = QUESTIONS[0]
    await safe_edit(
        c,
        f"Стресс 2.0 🧘\n\nВопрос 1/{len(QUESTIONS)}:\n{question}",
        _keyboard(0),
    )


@router.callback_query(F.data.regexp(r"^q:stress2:\d+:\d+$"))
async def quiz_stress2_step(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "stress2":
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

    rec_codes = ["VITEN", "OMEGA3", "TEO_GREEN"]
    lines = product_lines(rec_codes, ctx)

    actions = [
        "Дыхание 4-7-8 по 5 минут вечером.",
        "Утренний свет: 10–15 минут сразу после пробуждения.",
        "30 минут прогулки или растяжки каждый день.",
    ]
    notes = "Напоминай себе о перерывах каждые 90 минут и снижай кофеин после обеда."

    plan_payload = {
        "title": "План: стресс 2.0",
        "context": "stress",
        "context_name": "Стресс 2.0",
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
            {"quiz": "stress2", "score": total, "level": level_label},
        )
        await commit_safely(session)

    cards = pick_for_context("stress", level_key, rec_codes)
    await send_product_cards(
        c,
        f"Итог: {level_label}",
        cards,
        bullets=actions,
        headline=notes,
        back_cb="quiz:menu",
    )
    await send_premium_cta(
        c,
        "🔓 Еженедельные обновления доступны в Премиум",
        source="quiz:stress2",
    )
