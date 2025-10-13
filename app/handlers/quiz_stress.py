import datetime as dt

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.link_manager import get_register_link
from app.reco import product_lines
from app.repo import events as events_repo, retention as retention_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan
from app.utils.premium_cta import send_premium_cta

router = Router()

# ----------------------------
# ВОПРОСЫ КВИЗА «СТРЕСС»
# ----------------------------
STRESS_QUESTIONS = [
    (
        "Часто ли чувствуете внутреннее напряжение/тревогу?",
        [("Редко", 0), ("Иногда", 2), ("Часто", 4)],
    ),
    ("Есть ли раздражительность на мелочи?", [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    (
        "Как со сном из-за мыслей/стресса?",
        [("Засыпаю нормально", 0), ("Иногда мешает", 2), ("Часто мешает", 4)],
    ),
    (
        "Чувствуете мышечные зажимы (шея/плечи) или головные боли?",
        [("Нет", 0), ("Иногда", 2), ("Часто", 4)],
    ),
    ("Есть ли ощущение «эмоционального выгорания»?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _, answers = STRESS_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:stress:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def _stress_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 5:
        return (
            "mild",
            "\u0421\u0442\u0440\u0435\u0441\u0441 \u0432 \u043d\u043e\u0440\u043c\u0435",
            "stress_ok",
            ["OMEGA3", "T8_BLEND"],
        )
    if total <= 10:
        return (
            "moderate",
            "\u0423\u043c\u0435\u0440\u0435\u043d\u043d\u044b\u0439 \u0441\u0442\u0440\u0435\u0441\u0441",
            "stress_mid",
            ["MAG_B6", "OMEGA3"],
        )
    return (
        "severe",
        "\u0412\u044b\u0441\u043e\u043a\u0438\u0439 \u0441\u0442\u0440\u0435\u0441\u0441",
        "stress_high",
        ["MAG_B6", "OMEGA3", "T8_BLEND"],
    )


# ----------------------------
# СТАРТ КВИЗА
# ----------------------------


@router.callback_query(F.data == "quiz:stress")
async def quiz_stress_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "stress", "idx": 0, "score": 0}
    qtext, _ = STRESS_QUESTIONS[0]
    await safe_edit(
        c,
        f"Тест стресса 🧠\n\nВопрос 1/{len(STRESS_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(0),
    )


# ----------------------------
# ОБРАБОТКА ОТВЕТОВ
# ----------------------------


@router.callback_query(F.data.regexp(r"^q:stress:\d+:\d+$"))
async def quiz_stress_step(c: CallbackQuery):
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "stress":
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(STRESS_QUESTIONS):
        total = sess["score"]
        level_key, level_label, ctx, rec_codes = _stress_outcome(total)
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Экран-детокс 60 минут перед сном, дыхание 4–7–8.",
            "10 минут дневного света утром/днём.",
            "30 минут ходьбы или лёгкая тренировка ежедневно.",
        ]
        notes = "Избегай кофеина после 16:00. Добавь тёплый душ/растяжку вечером."

        discount_link = await get_register_link()

        plan_payload = {
            "title": "План: Стресс",
            "context": "stress",
            "context_name": "Стресс / нервная система",
            "level": level_label,
            "products": rec_codes[:3],
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": discount_link,
        }

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
            await set_last_plan(session, c.from_user.id, plan_payload)
            await events_repo.log(
                session,
                c.from_user.id,
                "quiz_finish",
                {"quiz": "stress", "score": total, "level": level_label},
            )
            await retention_repo.schedule_journey(
                session,
                c.from_user.id,
                "stress_relief",
                dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=48),
            )
            await commit_safely(session)

        cards = pick_for_context("stress", level_key, rec_codes[:3])
        await send_product_cards(
            c,
            f"Итог: {level_label}",
            cards,
            bullets=actions,
            headline=notes,
            back_cb="quiz:menu",
            utm_category="quiz_stress",
        )
        await send_premium_cta(
            c,
            "🔓 Еженедельные обновления доступны в Премиум",
            source="quiz:stress",
        )

        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = STRESS_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(STRESS_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )
