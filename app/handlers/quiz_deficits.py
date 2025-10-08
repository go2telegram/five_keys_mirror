"""Quiz for nutrient deficiencies (omega-3, magnesium, vitamin D)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.reco import product_lines
from app.repo import events as events_repo, quiz_results as quiz_results_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router(name="quiz_deficits")

_QUESTION_KEYS = ("omega", "mag", "vitd")

QUESTIONS: list[tuple[str, list[tuple[str, tuple[int, int, int]]]]] = [
    (
        "Сколько раз в неделю ешь жирную рыбу или морепродукты?",
        [("2+ раза", (0, 0, 0)), ("1 раз", (1, 0, 0)), ("Реже", (2, 0, 0))],
    ),
    (
        "Как часто в рационе есть орехи, семечки, зелень?",
        [("Каждый день", (0, 0, 0)), ("Пару раз в неделю", (0, 1, 0)), ("Редко", (0, 2, 0))],
    ),
    (
        "Бывают ли судороги, подёргивания век или мышечное напряжение?",
        [("Редко", (0, 0, 0)), ("Иногда", (0, 1, 0)), ("Часто", (0, 2, 0))],
    ),
    (
        "Сколько времени проводишь на солнце без SPF (днём)?",
        [("20+ минут", (0, 0, 0)), ("10–20 минут", (0, 0, 1)), ("<10 минут", (0, 0, 2))],
    ),
    (
        "Есть ли сезонное снижение настроения осенью/зимой?",
        [("Нет", (0, 0, 0)), ("Иногда", (0, 0, 1)), ("Да, заметно", (0, 0, 2))],
    ),
    (
        "Кожа/волосы: замечаешь сухость, шелушение, ломкость?",
        [("Нет", (0, 0, 0)), ("Иногда", (1, 0, 1)), ("Часто", (2, 0, 2))],
    ),
    (
        "Есть ли хроническое переутомление или стресс выше обычного?",
        [("Нет", (0, 0, 0)), ("Иногда", (1, 1, 0)), ("Да", (2, 2, 0))],
    ),
    (
        "Принимаешь ли добавки омега-3/магний/витамин D?",
        [
            ("Да, регулярно", (0, 0, 0)),
            ("Иногда курсами", (1, 1, 1)),
            ("Пока нет", (2, 2, 2)),
        ],
    ),
    (
        "Как часто бываешь на свежем воздухе днём (прогулки/спорт)?",
        [("Каждый день", (0, 0, 0)), ("2–3 раза в неделю", (1, 0, 1)), ("Редко", (2, 0, 2))],
    ),
    (
        "Питание: есть ли 3+ порции овощей/фруктов ежедневно?",
        [("Да", (0, 0, 0)), ("Иногда", (1, 1, 0)), ("Редко", (2, 2, 0))],
    ),
    (
        "Есть ли проблемы со сном (засыпание, частые пробуждения)?",
        [("Нет", (0, 0, 0)), ("Иногда", (0, 1, 0)), ("Да", (0, 2, 0))],
    ),
]


def _keyboard(idx: int) -> InlineKeyboardMarkup:
    text, answers = QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for pos, (label, _) in enumerate(answers):
        kb.button(text=label, callback_data=f"q:deficits:{idx}:{pos}")
    kb.button(text="⬅️ Назад", callback_data="quiz:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 2)
    return kb.as_markup()


def _level(score: int) -> str:
    if score <= 6:
        return "mild"
    if score <= 12:
        return "moderate"
    return "severe"


def _level_text(nutrient: str, level: str) -> str:
    mapping = {
        "omega": {
            "mild": "Омега-3 в комфортном диапазоне.",
            "moderate": "Добавь рыбу 2–3 раза и горсть орехов ежедневно.",
            "severe": "Высокий риск дефицита омега-3 — обсуди анализы и поддержку.",
        },
        "mag": {
            "mild": "Магний на уровне — продолжай балансировать стресс и сон.",
            "moderate": "Стоит добавить магний вечером и техники расслабления.",
            "severe": "Яркие признаки дефицита магния — полезно пройти курс и снизить стресс.",
        },
        "vitd": {
            "mild": "Витамин D покрыт солнцем или добавками.",
            "moderate": "Проверь 25(OH)D и добавь прогулки/поддержку.",
            "severe": "Высокий риск дефицита D — анализы и корректная дозировка обязательны.",
        },
    }
    return mapping[nutrient][level]


def _overall_level(levels: dict[str, str]) -> str:
    rank = {"mild": 0, "moderate": 1, "severe": 2}
    return max(levels.values(), key=lambda value: rank[value])


@router.callback_query(F.data == "quiz:deficits")
async def quiz_deficits_start(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {
        "quiz": "deficits",
        "idx": 0,
        "scores": {key: 0 for key in _QUESTION_KEYS},
    }
    question, _ = QUESTIONS[0]
    await safe_edit(
        c,
        f"Квиз: дефициты нутриентов 🩸\n\nВопрос 1/{len(QUESTIONS)}:\n{question}",
        _keyboard(0),
    )


@router.callback_query(F.data.regexp(r"^q:deficits:\d+:\d+$"))
async def quiz_deficits_step(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("quiz") != "deficits":
        await c.answer()
        return

    _, _, idx_s, choice_s = c.data.split(":")
    idx = int(idx_s)
    choice = int(choice_s)

    if idx >= len(QUESTIONS):
        await c.answer()
        return

    answers = QUESTIONS[idx][1]
    if choice < 0 or choice >= len(answers):
        await c.answer()
        return

    scores = answers[choice][1]
    for key, add in zip(_QUESTION_KEYS, scores, strict=False):
        sess["scores"][key] += add

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
    sess = SESSIONS.get(user_id)
    if not sess:
        await c.answer()
        return

    scores = sess["scores"]
    levels = {key: _level(value) for key, value in scores.items()}
    level_key = _overall_level(levels)
    level_label = {
        "mild": "Низкий риск дефицитов",
        "moderate": "Средний риск дефицитов",
        "severe": "Высокий риск дефицитов",
    }[level_key]

    summary = [
        _level_text("omega", levels["omega"]),
        _level_text("mag", levels["mag"]),
        _level_text("vitd", levels["vitd"]),
    ]

    rec_codes = ["OMEGA3", "MAG_B6", "D3"]
    context_key = {
        "mild": "deficit_low",
        "moderate": "deficit_mid",
        "severe": "deficit_high",
    }[level_key]
    lines = product_lines(rec_codes, context_key)

    actions = [
        "Добавь омега-3 (рыба/орехи) минимум 3 раза в неделю.",
        "Пей магний вечером курсом 4–6 недель и следи за расслаблением.",
        "Проверь витамин D раз в 6 месяцев и держи прогулки днём.",
    ]
    plan_payload = {
        "title": "План: дефициты нутриентов",
        "context": "deficits",
        "context_name": "Дефициты нутриентов",
        "level": level_label,
        "products": rec_codes,
        "lines": lines,
        "actions": actions,
        "notes": ("Рекомендации не заменяют анализы и консультацию врача.\n" + "\n".join(summary)),
        "order_url": settings.velavie_url,
    }

    total_score = sum(scores.values())

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, c.from_user.username)
        await set_last_plan(session, user_id, plan_payload)
        await events_repo.log(
            session,
            user_id,
            "quiz_finish",
            {
                "quiz": "deficits",
                "scores": scores,
                "levels": levels,
                "overall": level_key,
            },
        )
        await quiz_results_repo.save(
            session,
            user_id=user_id,
            quiz_name="deficits",
            score=total_score,
            tags={"levels": levels, "overall": level_key},
        )
        await commit_safely(session)

    cards = pick_for_context("deficit", level_key, rec_codes)
    await send_product_cards(
        c,
        f"Итог: {level_label}",
        cards,
        bullets=actions,
        headline="\n".join(summary),
        back_cb="quiz:menu",
    )

    SESSIONS.pop(user_id, None)
