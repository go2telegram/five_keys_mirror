from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.keyboards import kb_buylist_pdf
from app.storage import SESSIONS, USERS, save_event, set_last_plan
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

router = Router()

IMMUNITY_QUESTIONS = [
    ("Простужаетесь чаще 3 раз в год?", [
     ("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Болезни затягиваются дольше недели?", [
     ("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Есть постоянный стресс или недосып?", [
     ("Нет", 0), ("Иногда", 2), ("Да", 4)]),
    ("Бывают аллергии или высыпания?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    _, answers = IMMUNITY_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:immunity:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "quiz:immunity")
async def quiz_immunity_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "immunity", "idx": 0, "score": 0}
    qtext, _ = IMMUNITY_QUESTIONS[0]
    await c.message.edit_text(
        f"Тест иммунитета 🛡\n\nВопрос 1/{len(IMMUNITY_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(0),
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

        if total <= 4:
            level = "Хороший иммунитет"
            rec_codes = ["OMEGA3", "D3"]
            ctx = "immunity_good"
        elif total <= 8:
            level = "Средний уровень иммунитета"
            rec_codes = ["VITEN", "T8_BLEND"]
            ctx = "immunity_mid"
        else:
            level = "Иммунитет ослаблен"
            rec_codes = ["VITEN", "T8_BLEND", "D3"]
            ctx = "immunity_low"

        await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Сон 7–9 часов и регулярный режим.",
            "Прогулки ежедневно 30–40 минут.",
            "Белок 1.2–1.6 г/кг, овощи ежедневно.",
        ]
        notes = "В сезон простуд: тёплые напитки, влажность 40–60%, промывание носа."

        set_last_plan(
            c.from_user.id,
            {
                "title": "План: Иммунитет",
                "context": "immunity",
                "context_name": "Иммунитет",
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
            "• Сон 7–9 часов",
            "• Сбалансированное питание",
            "• Больше движения на свежем воздухе\n",
            "Поддержка:\n" + "\n".join(lines),
        ]
        await c.message.answer("\n".join(msg), reply_markup=kb_buylist_pdf("quiz:immunity", rec_codes[:3]))

        save_event(c.from_user.id, USERS[c.from_user.id].get("source"), "quiz_finish",
                   {"quiz": "immunity", "score": total, "level": level})
        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = IMMUNITY_QUESTIONS[idx]
    await c.message.edit_text(
        f"Вопрос {idx + 1}/{len(IMMUNITY_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(idx),
    )

