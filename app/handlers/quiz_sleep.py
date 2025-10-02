from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.reco import product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, set_last_plan

router = Router()

# ----------------------------
# ВОПРОСЫ КВИЗА «СОН»
# ----------------------------
SLEEP_QUESTIONS = [
    ("Ложитесь ли вы спать до 23:00?", [("Да", 0), ("Иногда", 2), ("Редко/Нет", 4)]),
    ("Сколько экранного времени перед сном (телефон, ТВ, ноут)?", [("<30 мин", 0), ("30–60 мин", 2), (">1 ч", 4)]),
    ("Пьёте кофеин (кофе/чай/энергетики) после 16:00?", [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Просыпаетесь ли ночью или тяжело засыпаете снова?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Чувствуете усталость даже после 7–8 ч сна?", [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _, answers = SLEEP_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:sleep:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def _sleep_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 5:
        return (
            "mild",
            "\u0421\u043e\u043d \u0432 \u043f\u043e\u0440\u044f\u0434\u043a\u0435",
            "sleep_ok",
            ["OMEGA3", "D3"],
        )
    if total <= 10:
        return (
            "moderate",
            "\u0415\u0441\u0442\u044c \u043d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u044f \u0441\u043d\u0430",
            "sleep_mild",
            ["MAG_B6", "OMEGA3"],
        )
    return (
        "severe",
        (
            "\u0421\u043e\u043d \u0441\u0435\u0440\u044c\u0451\u0437\u043d\u043e "
            "\u043d\u0430\u0440\u0443\u0448\u0435\u043d"
        ),
        "sleep_high",
        ["MAG_B6", "OMEGA3", "D3"],
    )


# ----------------------------
# СТАРТ КВИЗА
# ----------------------------


@router.callback_query(F.data == "quiz:sleep")
async def quiz_sleep_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "sleep", "idx": 0, "score": 0}
    qtext, _ = SLEEP_QUESTIONS[0]
    await safe_edit(
        c,
        f"Тест сна 😴\n\nВопрос 1/{len(SLEEP_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(0),
    )


# ----------------------------
# ОБРАБОТКА ОТВЕТОВ
# ----------------------------


@router.callback_query(F.data.regexp(r"^q:sleep:\d+:\d+$"))
async def quiz_sleep_step(c: CallbackQuery):
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "sleep":
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(SLEEP_QUESTIONS):
        total = sess["score"]
        level_key, level_label, ctx, rec_codes = _sleep_outcome(total)
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Экран-детокс за 60 минут до сна.",
            "Прохладная тёмная спальня (18–20°C, маска/шторы).",
            "Кофеин — не позже 16:00, ужин за 3 часа до сна.",
        ]
        notes = "Если сложно расслабиться — дыхание 4–7–8 или тёплый душ перед сном."

        plan_payload = {
            "title": "План: Сон",
            "context": "sleep",
            "context_name": "Сон",
            "level": level_label,
            "products": rec_codes[:3],
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": settings.VILAVI_ORDER_NO_REG,
        }

        async with session_scope() as session:
            await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
            await set_last_plan(session, c.from_user.id, plan_payload)
            await events_repo.log(
                session,
                c.from_user.id,
                "quiz_finish",
                {"quiz": "sleep", "score": total, "level": level_label},
            )
            await session.commit()

        cards = pick_for_context("sleep", level_key, rec_codes[:3])
        await send_product_cards(
            c,
            f"Итог: {level_label}",
            cards,
            bullets=actions,
            headline=notes,
            back_cb="quiz:menu",
        )

        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = SLEEP_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(SLEEP_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )
