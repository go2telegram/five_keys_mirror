from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.keyboards import kb_buylist_pdf
from app.storage import SESSIONS, USERS, save_event, set_last_plan
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

router = Router()

# ----------------------------
# ВОПРОСЫ КВИЗА «СТРЕСС»
# ----------------------------
STRESS_QUESTIONS = [
    ("Часто ли чувствуете внутреннее напряжение/тревогу?",
     [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Есть ли раздражительность на мелочи?", [
     ("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Как со сном из-за мыслей/стресса?",
     [("Засыпаю нормально", 0), ("Иногда мешает", 2), ("Часто мешает", 4)]),
    ("Чувствуете мышечные зажимы (шея/плечи) или головные боли?",
     [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Есть ли ощущение «эмоционального выгорания»?",
     [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    _, answers = STRESS_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:stress:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

# ----------------------------
# СТАРТ КВИЗА
# ----------------------------


@router.callback_query(F.data == "quiz:stress")
async def quiz_stress_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "stress", "idx": 0, "score": 0}
    qtext, _ = STRESS_QUESTIONS[0]
    await c.message.edit_text(
        f"Тест стресса 🧠\n\nВопрос 1/{len(STRESS_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(0),
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

        if total <= 5:
            level = "Стресс в норме"
            rec_codes = ["OMEGA3", "T8_BLEND"]
            ctx = "stress_ok"
        elif total <= 10:
            level = "Умеренный стресс"
            rec_codes = ["MAG_B6", "OMEGA3"]
            ctx = "stress_mid"
        else:
            level = "Высокий стресс"
            rec_codes = ["MAG_B6", "OMEGA3", "T8_BLEND"]
            ctx = "stress_high"

        await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Экран-детокс 60 минут перед сном, дыхание 4–7–8.",
            "10 минут дневного света утром/днём.",
            "30 минут ходьбы или лёгкая тренировка ежедневно.",
        ]
        notes = "Избегай кофеина после 16:00. Добавь тёплый душ/растяжку вечером."

        set_last_plan(
            c.from_user.id,
            {
                "title": "План: Стресс",
                "context": "stress",
                "context_name": "Стресс / нервная система",
                "level": level,
                "products": rec_codes[:3],
                "lines": lines,
                "actions": actions,
                "notes": notes,
                "order_url": settings.VILAVI_ORDER_NO_REG,
            }
        )

        msg = [
            f"Итог: <b>{level}</b>\n",
            "Что важно делать:",
            "• Экран-детокс 60 мин перед сном, дыхание 4–7–8",
            "• Дневной свет 10 мин, прогулка 30 мин",
            "• Кофеин до 16:00; тёплый душ/растяжка вечером\n",
            "Поддержка:\n" + "\n".join(lines),
        ]
        await c.message.answer("\n".join(msg), reply_markup=kb_buylist_pdf("quiz:stress", rec_codes[:3]))

        save_event(c.from_user.id, USERS[c.from_user.id].get("source"), "quiz_finish",
                   {"quiz": "stress", "score": total, "level": level})
        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = STRESS_QUESTIONS[idx]
    await c.message.edit_text(
        f"Вопрос {idx + 1}/{len(STRESS_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(idx),
    )

