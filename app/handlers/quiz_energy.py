from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.keyboards import kb_buylist_pdf
from app.storage import SESSIONS, save_event, set_last_plan, get_user
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

router = Router()

ENERGY_QUESTIONS = [
    ("Сколько часов ты спишь обычно?", [
     ("8+ ч", 0), ("6–7 ч", 2), ("< 6 ч", 4)]),
    ("Есть «туман в голове» и сложно фокусироваться?",
     [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Тяга к сладкому/быстрым перекусам?",
     [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Холодные руки/ноги без причины?",
     [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Долго восстанавливаешься после нагрузок/болезни?",
     [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
]


def kb_quiz_q(idx: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    _, answers = ENERGY_QUESTIONS[idx]
    kb = InlineKeyboardBuilder()
    for label, score in answers:
        kb.button(text=label, callback_data=f"q:energy:{idx}:{score}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "quiz:energy")
async def quiz_energy_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "energy", "idx": 0, "score": 0}
    qtext, _ = ENERGY_QUESTIONS[0]
    await c.message.edit_text(
        f"Тест энергии ⚡\n\nВопрос 1/{len(ENERGY_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(0),
    )


@router.callback_query(F.data.regexp(r"^q:energy:\d+:\d+$"))
async def quiz_energy_step(c: CallbackQuery):
    sess = SESSIONS.get(c.from_user.id, {})
    if sess.get("quiz") != "energy":
        return

    _, _, idx_s, score_s = c.data.split(":")
    idx = int(idx_s)
    score = int(score_s)
    sess["score"] += score
    idx += 1

    if idx >= len(ENERGY_QUESTIONS):
        total = sess["score"]

        if total <= 5:
            level = "Норма"
            rec_codes = ["OMEGA3", "VITEN"]
            ctx = "energy_norm"
        elif total <= 10:
            level = "Лёгкая усталость"
            rec_codes = ["T8_BLEND", "VITEN", "TEO_GREEN"]
            ctx = "energy_light"
        else:
            level = "Выраженная усталость"
            rec_codes = ["T8_EXTRA", "VITEN", "MOBIO"]
            ctx = "energy_high"

        await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Ложиться до 23:00 и спать 7–9 часов.",
            "10 минут утреннего света (балкон/улица).",
            "30 минут быстрой ходьбы ежедневно.",
        ]
        notes = "Следи за гидратацией: 30–35 мл воды/кг. Ужин — за 3 часа до сна."

        await set_last_plan(
            c.from_user.id,
            {
                "title": "План: Энергия",
                "context": "energy",
                "context_name": "Энергия",
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
            "Что можно сделать уже сегодня:",
            "• Сон до 23:00, 7–9 ч",
            "• 10 мин утреннего света",
            "• 30 мин быстрой ходьбы\n",
            "Поддержка:\n" + "\n".join(lines),
        ]
        await c.message.answer("\n".join(msg), reply_markup=kb_buylist_pdf("quiz:energy", rec_codes[:3]))

        profile = await get_user(c.from_user.id)
        await save_event(
            c.from_user.id,
            profile.source if profile else None,
            "quiz_finish",
            {"quiz": "energy", "score": total, "level": level},
        )
        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = ENERGY_QUESTIONS[idx]
    await c.message.edit_text(
        f"Вопрос {idx + 1}/{len(ENERGY_QUESTIONS)}:\n{qtext}",
        reply_markup=kb_quiz_q(idx),
    )
