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

ENERGY_QUESTIONS = [
    ("Сколько часов ты спишь обычно?", [("8+ ч", 0), ("6–7 ч", 2), ("< 6 ч", 4)]),
    ("Есть «туман в голове» и сложно фокусироваться?", [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Тяга к сладкому/быстрым перекусам?", [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Холодные руки/ноги без причины?", [("Нет", 0), ("Иногда", 2), ("Часто", 4)]),
    ("Долго восстанавливаешься после нагрузок/болезни?", [("Нет", 0), ("Иногда", 2), ("Да", 4)]),
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


def _energy_outcome(total: int) -> tuple[str, str, str, list[str]]:
    if total <= 5:
        return (
            "mild",
            "\u042d\u043d\u0435\u0440\u0433\u0438\u044f \u0432 \u043d\u043e\u0440\u043c\u0435",
            "energy_norm",
            ["T8_BLEND", "OMEGA3", "VITEN"],
        )
    if total <= 10:
        return (
            "moderate",
            "\u041b\u0451\u0433\u043a\u0430\u044f \u0443\u0441\u0442\u0430\u043b\u043e\u0441\u0442\u044c",
            "energy_light",
            ["T8_BLEND", "VITEN", "TEO_GREEN"],
        )
    return (
        "severe",
        (
            "\u0412\u044b\u0440\u0430\u0436\u0435\u043d\u043d\u0430\u044f "
            "\u0443\u0441\u0442\u0430\u043b\u043e\u0441\u0442\u044c"
        ),
        "energy_high",
        ["T8_EXTRA", "VITEN", "MOBIO"],
    )


@router.callback_query(F.data == "quiz:energy")
async def quiz_energy_start(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"quiz": "energy", "idx": 0, "score": 0}
    qtext, _ = ENERGY_QUESTIONS[0]
    await safe_edit(
        c,
        f"Тест энергии ⚡\n\nВопрос 1/{len(ENERGY_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(0),
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
        level_key, level_label, ctx, rec_codes = _energy_outcome(total)
        lines = product_lines(rec_codes[:3], ctx)

        actions = [
            "Ложиться до 23:00 и спать 7–9 часов.",
            "10 минут утреннего света (балкон/улица).",
            "30 минут быстрой ходьбы ежедневно.",
        ]
        notes = "Следи за гидратацией: 30–35 мл воды/кг. Ужин — за 3 часа до сна."

        plan_payload = {
            "title": "План: Энергия",
            "context": "energy",
            "context_name": "Энергия",
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
                {"quiz": "energy", "score": total, "level": level_label},
            )
            await session.commit()

        cards = pick_for_context("energy", level_key, rec_codes[:3])
        await send_product_cards(
            c,
            f"Итог: {level_label}",
            cards,
        )

        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = ENERGY_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(ENERGY_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )
