"""Macro-nutrient calculator."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.calc_common import log_calc_error, send_calc_summary
from app.keyboards import kb_back_home
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router(name="calc_macros")

_GOAL_LABELS: dict[str, str] = {
    "loss": "Жиросжигание",
    "maintain": "Поддержание",
    "gain": "Набор массы",
}

_PREFERENCE_LABELS: dict[str, tuple[str, float, float]] = {
    "balanced": ("Сбалансированное питание", 1.6, 0.9),
    "lowcarb": ("Сниженные углеводы", 1.4, 1.0),
    "highprotein": ("Высокобелковый подход", 2.0, 0.8),
}


@router.callback_query(F.data == "calc:macros")
async def start_macros(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {"calc": "macros", "step": "weight"}
    await c.answer()
    await c.message.edit_text(
        "Укажи текущий вес в килограммах (например, <code>68</code>):",
        reply_markup=kb_back_home("calc:menu"),
    )


async def handle_message(message: Message) -> bool:
    sess = SESSIONS.get(message.from_user.id)
    if not sess or sess.get("calc") != "macros":
        return False

    if sess.get("step") != "weight":
        return True

    text = (message.text or "").strip().replace(",", ".")
    try:
        weight = float(text)
    except ValueError:
        weight = 0.0

    if weight <= 30 or weight > 250:
        await log_calc_error(
            message.from_user.id if message.from_user else None,
            calc="macros",
            step="weight",
            reason="invalid_value",
            raw_input=message.text,
        )
        await message.answer(
            "Вес должен быть числом от 30 до 250 кг.",
            reply_markup=kb_back_home("calc:menu"),
        )
        return True

    sess["weight"] = weight
    sess["step"] = "goal"
    kb = InlineKeyboardBuilder()
    kb.button(text="Жиросжигание", callback_data="calc:macros:goal:loss")
    kb.button(text="Поддержание", callback_data="calc:macros:goal:maintain")
    kb.button(text="Набор массы", callback_data="calc:macros:goal:gain")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2, 1, 2)
    await message.answer("Какая цель?", reply_markup=kb.as_markup())
    return True


def _target_calories(weight: float, goal: str) -> int:
    maintenance = weight * 30.0
    if goal == "loss":
        return round(maintenance * 0.85)
    if goal == "gain":
        return round(maintenance * 1.1)
    return round(maintenance)


def _macros(weight: float, goal: str, preference: str) -> tuple[int, int, int, int]:
    calories = _target_calories(weight, goal)
    pref = _PREFERENCE_LABELS.get(preference, _PREFERENCE_LABELS["balanced"])
    protein = max(1.2, pref[1]) * weight
    fats = max(0.7, pref[2]) * weight
    carbs_calories = max(0.0, calories - protein * 4 - fats * 9)
    carbs = carbs_calories / 4

    def _round(value: float) -> int:
        return int(round(value / 5.0) * 5)

    return (
        calories,
        _round(protein),
        _round(fats),
        max(0, _round(carbs)),
    )


def _bullets(goal: str) -> list[str]:
    messages = {
        "loss": "Добавь силовые 2–3 раза в неделю и шаги 8–10 тыс.",
        "maintain": "Держи белок в каждом приёме пищи, следи за водой и сном.",
        "gain": "Фокус на прогресс в силовых и качественный сон 7–9 часов.",
    }
    return [
        messages.get(goal, messages["maintain"]),
        "Планируй приёмы пищи заранее и делай замеры раз в 2 недели.",
        "Добавь клетчатку (овощи/TEO GREEN), чтобы держать аппетит под контролем.",
    ]


async def _finalize(
    c: CallbackQuery,
    calories: int,
    protein: int,
    fats: int,
    carbs: int,
    goal: str,
) -> None:
    sess = SESSIONS.get(c.from_user.id, {})
    weight = float(sess.get("weight", 0.0))
    preference = sess.get("preference", "balanced")

    rec_codes = ["OMEGA3", "T8_BLEND", "TEO_GREEN"]
    cards = pick_for_context("calc_macros", goal, rec_codes)
    bullets = _bullets(goal)

    plan_payload = {
        "title": "План: белки/жиры/углеводы",
        "context": "calc_macros",
        "context_name": "Калькулятор БЖУ",
        "level": goal,
        "products": rec_codes,
        "lines": [
            f"— Калории: {calories} ккал",
            f"— Белки: {protein} г",
            f"— Жиры: {fats} г",
            f"— Углеводы: {carbs} г",
        ],
        "actions": bullets,
        "notes": "Подбирай меню вместе со специалистом при хронических состояниях.",
        "order_url": settings.velavie_url,
    }

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        await set_last_plan(session, c.from_user.id, plan_payload)
        await events_repo.log(
            session,
            c.from_user.id,
            "calc_finish",
            {
                "calc": "macros",
                "calories": calories,
                "protein": protein,
                "fats": fats,
                "carbs": carbs,
                "goal": goal,
                "preference": preference,
                "weight": weight,
            },
        )
        await commit_safely(session)

    goal_label = _GOAL_LABELS.get(goal, "Поддержание")
    await send_calc_summary(
        c,
        calc="macros",
        title="🥗 Баланс БЖУ",
        summary=[
            f"Калории: <b>{calories} ккал</b>",
            f"Б/Ж/У: <b>{protein} г</b> / <b>{fats} г</b> / <b>{carbs} г</b>",
            f"Цель: {goal_label}",
        ],
        products=cards,
        headline=(
            f"Калории: <b>{calories} ккал</b>. Белки: <b>{protein} г</b>,"
            f" жиры: <b>{fats} г</b>, углеводы: <b>{carbs} г</b>."
        ),
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(c.from_user.id, None)


@router.callback_query(F.data.startswith("calc:macros:goal:"))
async def choose_goal(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "macros":
        await c.answer()
        return

    goal = c.data.split(":")[-1]
    if goal not in _GOAL_LABELS:
        await c.answer()
        return

    sess["goal"] = goal
    sess["step"] = "preference"
    await c.answer()
    kb = InlineKeyboardBuilder()
    for key, (title, _, _) in _PREFERENCE_LABELS.items():
        kb.button(text=title, callback_data=f"calc:macros:pref:{key}")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 2)
    await c.message.answer(
        "Какой формат питания ближе?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("calc:macros:pref:"))
async def choose_preference(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "macros":
        await c.answer()
        return

    pref = c.data.split(":")[-1]
    if pref not in _PREFERENCE_LABELS:
        await c.answer()
        return

    goal = sess.get("goal", "maintain")
    weight = float(sess.get("weight") or 0.0)
    if weight <= 0:
        await c.answer()
        await log_calc_error(
            c.from_user.id if c.from_user else None,
            calc="macros",
            step="preference",
            reason="missing_weight",
        )
        await c.message.answer(
            "Вес не указан. Запусти расчёт заново.",
            reply_markup=kb_back_home("calc:menu"),
        )
        SESSIONS.pop(c.from_user.id, None)
        return

    sess["preference"] = pref
    calories, protein, fats, carbs = _macros(weight, goal, pref)
    await _finalize(c, calories, protein, fats, carbs, goal)


__all__ = ["router", "handle_message"]
