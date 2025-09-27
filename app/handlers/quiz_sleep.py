from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.keyboards import kb_buylist_pdf
from app.storage import SESSIONS, USERS, save_event, set_last_plan
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

router = Router()

# ----------------------------
# ВОПРОСЫ КВИЗА «СОН»
# ----------------------------
SLEEP_QUESTIONS = [
    ("Ложитесь ли вы спать до 23:00?", [
     ("Да", 0), ("Иногда", 2), ("Редко/Нет", 4)]),
    ("Сколько экранного времени перед сном (телефон, ТВ, ноут)?",
     [("<30 мин", 0), ("30–60 мин", 2), (">1 ч", 4)]),
    ("Пьёте кофеин (кофе/чай/энергетики) после 16:00?",
     [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Просыпаетесь ли ночью или тяжело засыпаете снова?",
     [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Чувствуете усталость даже после 7–8 ч сна?",
     [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    _, answers = SLEEP_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:sleep:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

# ----------------------------
# СТАРТ КВИЗА
# ----------------------------


@router.callback_query(F.data == "quiz:sleep")
async def quiz_sleep_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "sleep", "idx": 0, "score": 0}
    qtext, _ = SLEEP_QUESTIONS[0]
    await c.message.edit_text(
        f"Тест сна 😴\n\nВопрос 1/{len(SLEEP_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(0),
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

        if total <= 5:
            level = "Сон в порядке"
            rec_codes = ["OMEGA3", "D3"]
            ctx = "sleep_ok"
        elif total <= 10:
            level = "Есть нарушения сна"
            rec_codes = ["MAG_B6", "OMEGA3"]
            ctx = "sleep_mild"
        else:
            level = "Сон серьёзно нарушен"
            rec_codes = ["MAG_B6", "OMEGA3", "D3"]
            ctx = "sleep_high"

        await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Экран-детокс за 60 минут до сна.",
            "Прохладная тёмная спальня (18–20°C, маска/шторы).",
            "Кофеин — не позже 16:00, ужин за 3 часа до сна.",
        ]
        notes = "Если сложно расслабиться — дыхание 4–7–8 или тёплый душ перед сном."

        set_last_plan(
            c.from_user.id,
            {
                "title": "План: Сон",
                "context": "sleep",
                "context_name": "Сон",
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
            "• Ложиться до 23:00",
            "• Минимизировать экраны за 1 ч до сна",
            "• Кофеин только до 16:00",
            "• Проветрить комнату и убрать лишний свет\n",
            "Поддержка:\n" + "\n".join(lines),
        ]
        await c.message.answer("\n".join(msg), reply_markup=kb_buylist_pdf("quiz:sleep", rec_codes[:3]))

        save_event(c.from_user.id, USERS[c.from_user.id].get("source"), "quiz_finish",
                   {"quiz": "sleep", "score": total, "level": level})
        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = SLEEP_QUESTIONS[idx]
    await c.message.edit_text(
        f"Вопрос {idx + 1}/{len(SLEEP_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(idx),
    )

