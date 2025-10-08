from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.reco import personalize_codes, product_lines
from app.repo import events as events_repo, profiles as profiles_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router()

IMMUNITY_QUESTIONS = [
    ("Простужаетесь чаще 3 раз в год?", [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Болезни затягиваются дольше недели?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Есть постоянный стресс или недосып?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Бывают аллергии или высыпания?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _, answers = IMMUNITY_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:immunity:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def _immunity_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 4:
        return (
            "mild",
            "\u0425\u043e\u0440\u043e\u0448\u0438\u0439 \u0438\u043c\u043c\u0443\u043d\u0438\u0442\u0435\u0442",
            "immunity_good",
            ["OMEGA3", "D3"],
        )
    if total <= 8:
        return (
            "moderate",
            (
                "\u0421\u0440\u0435\u0434\u043d\u0438\u0439 \u0443\u0440\u043e\u0432\u0435\u043d\u044c "
                "\u0438\u043c\u043c\u0443\u043d\u0438\u0442\u0435\u0442\u0430"
            ),
            "immunity_mid",
            ["VITEN", "T8_BLEND"],
        )
    return (
        "severe",
        ("\u0418\u043c\u043c\u0443\u043d\u0438\u0442\u0435\u0442 " "\u043e\u0441\u043b\u0430\u0431\u043b\u0451\u043d"),
        "immunity_low",
        ["VITEN", "T8_BLEND", "D3"],
    )


@router.callback_query(F.data == "quiz:immunity")
async def quiz_immunity_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "immunity", "idx": 0, "score": 0}
    qtext, _ = IMMUNITY_QUESTIONS[0]
    await safe_edit(
        c,
        f"Тест иммунитета 🛡\n\nВопрос 1/{len(IMMUNITY_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(0),
    )


@router.callback_query(F.data.regexp(r"^q:immunity:\d+:\d+$"))
async def quiz_immunity_step(c: CallbackQuery):
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "immunity":
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(IMMUNITY_QUESTIONS):
        total = sess["score"]
        level_key, level_label, ctx, rec_codes = _immunity_outcome(total)

        actions = [
            "Сон 7–9 часов и регулярный режим.",
            "Прогулки ежедневно 30–40 минут.",
            "Белок 1.2–1.6 г/кг, овощи ежедневно.",
        ]
        notes = "В сезон простуд: тёплые напитки, влажность 40–60%, промывание носа."

        personalized_codes: list[str]
        lines: list[str]

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
            profile_data = await profiles_repo.get_profile_data(session, c.from_user.id)
            personalized_codes = personalize_codes(rec_codes, profile_data)
            if not personalized_codes:
                personalized_codes = rec_codes[:3]
            lines = product_lines(personalized_codes, ctx)
            plan_payload = {
                "title": "План: Иммунитет",
                "context": "immunity",
                "context_name": "Иммунитет",
                "level": level_label,
                "products": personalized_codes,
                "lines": lines,
                "actions": actions,
                "notes": notes,
                "order_url": settings.velavie_url,
            }
            await set_last_plan(session, c.from_user.id, plan_payload)
            await events_repo.log(
                session,
                c.from_user.id,
                "quiz_finish",
                {"quiz": "immunity", "score": total, "level": level_label},
            )
            await commit_safely(session)

        cards = pick_for_context("immunity", level_key, personalized_codes)
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

    qtext, _ = IMMUNITY_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(IMMUNITY_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )
