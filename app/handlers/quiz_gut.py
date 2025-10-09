from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.keyboards import kb_recommend_follow_up
from app.reco import product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan
from app.utils.premium_cta import send_premium_cta

router = Router()

# ----------------------------
# ВОПРОСЫ КВИЗА «ЖКТ / микробиом»
# ----------------------------
GUT_QUESTIONS = [
    ("Часто бывает вздутие или тяжесть после еды?", [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Стул нерегулярный (реже 1 раза в день / запоры / нестабильный)?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Тянет на сладкое/перекусы, сложно контролировать аппетит?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Недавно были антибиотики/острые инфекции/стрессы?", [("Нет", 0), ("За 3–6 мес", 2), ("За последний месяц", 4)]),
    ("Изжога/рефлюкс/дискомфорт в верхних отделах ЖКТ?", [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _, answers = GUT_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:gut:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def _gut_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 5:
        return (
            "mild",
            "\u0411\u0430\u043b\u0430\u043d\u0441 \u0432 \u043f\u043e\u0440\u044f\u0434\u043a\u0435",
            "gut_ok",
            ["TEO_GREEN", "OMEGA3"],
        )
    if total <= 10:
        return (
            "moderate",
            (
                "\u041b\u0451\u0433\u043a\u0438\u0435 \u043d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u044f "
                "\u043c\u0438\u043a\u0440\u043e\u0431\u0438\u043e\u043c\u0430"
            ),
            "gut_mild",
            ["TEO_GREEN", "MOBIO"],
        )
    return (
        "severe",
        "\u0416\u041a\u0422 \u043f\u043e\u0434 \u043d\u0430\u0433\u0440\u0443\u0437\u043a\u043e\u0439",
        "gut_high",
        ["MOBIO", "TEO_GREEN", "OMEGA3"],
    )


# ----------------------------
# СТАРТ КВИЗА
# ----------------------------
@router.callback_query(F.data == "quiz:gut")
async def quiz_gut_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "gut", "idx": 0, "score": 0}
    qtext, _ = GUT_QUESTIONS[0]
    await safe_edit(
        c,
        f"Тест ЖКТ / микробиом 🌿\n\nВопрос 1/{len(GUT_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(0),
    )


# ----------------------------
# ОБРАБОТКА ОТВЕТОВ
# ----------------------------
@router.callback_query(F.data.regexp(r"^q:gut:\d+:\d+$"))
async def quiz_gut_step(c: CallbackQuery):
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "gut":
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(GUT_QUESTIONS):
        total = sess["score"]
        level_key, level_label, ctx, rec_codes = _gut_outcome(total)
        lines = product_lines(rec_codes[:3], ctx)

        # 3) план для PDF
        actions = [
            "Регулярный режим питания (без «донышек»).",
            "Клетчатка ежедневно (TEO GREEN) + вода 30–35 мл/кг.",
            "Минимизируй сахар и ультра-обработанные продукты.",
        ]
        notes = "Если были антибиотики — курс MOBIO поможет быстрее восстановиться."

        plan_payload = {
            "title": "План: ЖКТ / микробиом",
            "context": "gut",
            "context_name": "ЖКТ / микробиом",
            "level": level_label,
            "products": rec_codes[:3],
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": settings.velavie_url,
        }

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
            await set_last_plan(session, c.from_user.id, plan_payload)
            await events_repo.log(
                session,
                c.from_user.id,
                "quiz_finish",
                {"quiz": "gut", "score": total, "level": level_label},
            )
            await commit_safely(session)

        cards = pick_for_context("gut", level_key, rec_codes[:3])
        await send_product_cards(
            c,
            f"Итог: {level_label}",
            cards,
            bullets=actions,
            headline=notes,
            back_cb="quiz:menu",
            follow_up=("Что дальше?", kb_recommend_follow_up()),
        )
        await send_premium_cta(
            c,
            "🔓 Еженедельные обновления доступны в Премиум",
            source="quiz:gut",
        )

        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = GUT_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(GUT_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )
