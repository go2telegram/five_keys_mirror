from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import safe_edit, send_product_cards
from app.products import GOAL_MAP
from app.quiz.engine import (
    QuizDefinition,
    QuizHooks,
    QuizResultContext,
    register_quiz_hooks,
)
from app.reco import product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan
from app.services import get_reco
from app.utils.nav import nav_footer
from app.utils.premium_cta import send_premium_cta
from app.utils.sender import chat_sender

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
    (
        "Ложитесь и просыпаетесь ли в одно и то же время (±30 мин)?",
        [("Да", 0), ("Иногда", 2), ("Нет", 4)],
    ),
    (
        "Получаете ли 10–15 минут дневного света в течение часа после пробуждения?",
        [("Да", 0), ("Иногда", 2), ("Редко", 4)],
    ),
    (
        "Используете ли кровать только для сна и отдыха (без работы и сериалов)?",
        [("Да", 0), ("Иногда", 2), ("Часто", 4)],
    ),
    ("Бывают ли тяжёлые ужины/перекусы позднее чем за 2 часа до сна?", [("Редко", 0), ("Иногда", 2), ("Часто", 4)]),
]


def _merge_tags(result: QuizResultContext) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (result.threshold.tags, result.collected_tags):
        for tag in source or []:
            normalized = str(tag).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _register_yaml_hooks() -> None:
    async def _on_finish_sleep(
        user_id: int, definition: QuizDefinition, result: QuizResultContext
    ) -> bool:
        origin = result.origin
        message = origin.message if origin and origin.message else None
        if not message:
            return False

        chat_id = message.chat.id
        tags = _merge_tags(result)
        products = await get_reco(
            user_id,
            limit=3,
            source="quiz:sleep",
            tags=tags,
        )
        if not products:
            products = GOAL_MAP.get("sleep", [])

        selected_products = list(products)[:3]
        title = f"Итог: {result.threshold.label}"
        headline = result.threshold.advice

        await chat_sender.send_sequence(
            chat_id,
            chat_sender.chat_action(chat_id, "typing"),
            lambda: send_product_cards(
                origin,
                title,
                selected_products,
                ctx="sleep",
                headline=headline,
                back_cb="menu:tests",
            ),
            chat_sender.send_text(chat_id, "Главное меню", reply_markup=nav_footer()),
        )
        return True

    register_quiz_hooks("sleep", QuizHooks(on_finish=_on_finish_sleep))


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
    if total <= 8:
        return (
            "mild",
            "\u0421\u043e\u043d \u0432 \u043f\u043e\u0440\u044f\u0434\u043a\u0435",
            "sleep_ok",
            ["OMEGA3", "D3"],
        )
    if total <= 16:
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
            "Экран-детокс за 60 минут до сна и мягкий свет.",
            "Фиксируй время отбоя/подъёма в пределах ±30 минут.",
            "10 минут утреннего света и короткая прогулка днём.",
            "Лёгкий ужин за 3 часа до сна, кофеин — не позже 14:00.",
        ]
        notes = "Для расслабления — дыхание 4–7–8, тёплый душ и проветривание спальни."

        plan_payload = {
            "title": "План: Сон",
            "context": "sleep",
            "context_name": "Сон",
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
                {"quiz": "sleep", "score": total, "level": level_label},
            )
            await commit_safely(session)

        cards = pick_for_context("sleep", level_key, rec_codes[:3])
        await send_product_cards(
            c,
            f"Итог: {level_label}",
            cards,
            bullets=actions,
            headline=notes,
            back_cb="quiz:menu",
        )
        await send_premium_cta(
            c,
            "🔓 Еженедельные обновления доступны в Премиум",
            source="quiz:sleep",
        )

        SESSIONS.pop(c.from_user.id, None)
        return

    qtext, _ = SLEEP_QUESTIONS[idx]
    await safe_edit(
        c,
        f"Вопрос {idx + 1}/{len(SLEEP_QUESTIONS)}:\n{qtext}",
        kb_quiz_q(idx),
    )


_register_yaml_hooks()
