from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.keyboards import kb_buylist_pdf
from app.storage import SESSIONS, USERS, save_event, set_last_plan
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

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
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()

# ----------------------------
# СТАРТ КВИЗА
# ----------------------------
@router.callback_query(F.data == "quiz:gut")
async def quiz_gut_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "gut", "idx": 0, "score": 0}
    qtext, _ = GUT_QUESTIONS[0]
    await c.message.edit_text(
        f"Тест ЖКТ / микробиом 🌿\n\nВопрос 1/{len(GUT_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(0),
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

        if total <= 5:
            level = "Баланс в порядке"
            rec_codes = ["TEO_GREEN", "OMEGA3"]; ctx = "gut_ok"
        elif total <= 10:
            level = "Лёгкие нарушения микробиома"
            rec_codes = ["TEO_GREEN", "MOBIO"]; ctx = "gut_mild"
        else:
            level = "ЖКТ под нагрузкой"
            rec_codes = ["MOBIO", "TEO_GREEN", "OMEGA3"]; ctx = "gut_high"

        # 1) фото
        await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])

        # 2) карточка
        lines = product_lines(rec_codes[:3], ctx)

        # 3) план для PDF
        actions = [
            "Регулярный режим питания (без «донышек»).",
            "Клетчатка ежедневно (TEO GREEN) + вода 30–35 мл/кг.",
            "Минимизируй сахар и ультра-обработанные продукты.",
        ]
        notes = "Если были антибиотики — курс MOBIO поможет быстрее восстановиться."

        set_last_plan(
            c.from_user.id,
            {
                "title": "План: ЖКТ / микробиом",
                "context": "gut",
                "context_name": "ЖКТ / микробиом",
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
            "Что важно делать уже сегодня:",
            "• Регулярный режим питания, без «донышек» и частых перекусов",
            "• Вода 30–35 мл/кг и прогулки 30 мин в день",
            "• Добавить клетчатку и белок в основной приём пищи\n",
            "Поддержка:\n" + "\n".join(lines),
        ]
        await c.message.answer("\n".join(msg), reply_markup=kb_buylist_pdf("quiz:gut", rec_codes[:3]))

        save_event(c.from_user.id, USERS[c.from_user.id].get("source"), "quiz_finish",
                   {"quiz": "gut", "score": total, "level": level})
        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = GUT_QUESTIONS[idx]
    await c.message.edit_text(
        f"Вопрос {idx + 1}/{len(GUT_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(idx),
    )

