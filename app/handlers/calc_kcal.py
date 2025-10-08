"""Calorie calculator (BMR/TDEE)."""

from __future__ import annotations

from typing import Literal

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers import calc_unified
from app.handlers.quiz_common import send_product_cards
from app.keyboards import kb_back_home
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router(name="calc_kcal")

_ACTIVITY_FACTORS: dict[str, tuple[str, float]] = {
    "12": ("Минимальная активность", 1.2),
    "1375": ("Лёгкие тренировки 1–3 раза в неделю", 1.375),
    "155": ("Умеренные тренировки 3–5 раз", 1.55),
    "1725": ("Интенсивные тренировки 6–7 раз", 1.725),
    "19": ("Очень высокая активность", 1.9),
}

_GOAL_LABELS: dict[str, str] = {
    "loss": "Снижение веса",
    "maintain": "Поддержание",
    "gain": "Набор массы",
}


@router.callback_query(F.data == "calc:kcal")
async def start_kcal(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {"calc": "kcal", "step": "sex"}
    await c.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="Мужчина", callback_data="calc:kcal:sex:m")
    kb.button(text="Женщина", callback_data="calc:kcal:sex:f")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2, 2)
    await c.message.edit_text("Выбери пол:", reply_markup=kb.as_markup())


async def handle_message(message: Message) -> bool:
    sess = SESSIONS.get(message.from_user.id)
    if not sess or sess.get("calc") != "kcal":
        return False

    step = sess.get("step")
    text = (message.text or "").strip()
    if step == "age":
        if not text.isdigit():
            await message.answer(
                "Возраст должен быть числом лет. Пример: <code>32</code>",
                reply_markup=kb_back_home("calc:menu"),
            )
            return True
        age = int(text)
        if age < 14 or age > 90:
            await message.answer(
                "Укажи возраст от 14 до 90 лет.",
                reply_markup=kb_back_home("calc:menu"),
            )
            return True
        sess["age"] = age
        sess["step"] = "weight"
        await message.answer(
            "Теперь вес в килограммах (например, <code>78.5</code>):",
            reply_markup=kb_back_home("calc:menu"),
        )
        return True

    if step == "weight":
        try:
            weight = float(text.replace(",", "."))
        except ValueError:
            weight = 0.0
        if weight <= 30 or weight > 250:
            await message.answer(
                "Вес должен быть числом от 30 до 250 кг.",
                reply_markup=kb_back_home("calc:menu"),
            )
            return True
        sess["weight"] = weight
        sess["step"] = "height"
        await message.answer(
            "Укажи рост в сантиметрах (например, <code>175</code>):",
            reply_markup=kb_back_home("calc:menu"),
        )
        return True

    if step == "height":
        if not text.isdigit():
            await message.answer(
                "Рост должен быть целым числом сантиметров.",
                reply_markup=kb_back_home("calc:menu"),
            )
            return True
        height = int(text)
        if height < 130 or height > 220:
            await message.answer(
                "Рост в диапазоне 130–220 см.",
                reply_markup=kb_back_home("calc:menu"),
            )
            return True
        sess["height"] = height
        sess["step"] = "activity"
        kb = InlineKeyboardBuilder()
        for key, (title, _) in _ACTIVITY_FACTORS.items():
            kb.button(text=title, callback_data=f"calc:kcal:activity:{key}")
        kb.button(text="⬅️ Назад", callback_data="calc:menu")
        kb.button(text="🏠 Домой", callback_data="home:main")
        kb.adjust(1, 1, 1, 1, 2)
        await message.answer(
            "Выбери уровень активности:",
            reply_markup=kb.as_markup(),
        )
        return True

    return True


def _compute(  # noqa: PLR0913 - explicit formula parameters
    sex: Literal["m", "f"],
    age: int,
    weight: float,
    height: int,
    factor: float,
    goal: Literal["loss", "maintain", "gain"],
) -> tuple[int, int, int]:
    base = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "m" else -161)
    tdee = base * factor
    if goal == "loss":
        target = tdee * 0.85
    elif goal == "gain":
        target = tdee * 1.1
    else:
        target = tdee
    return round(base), round(tdee), round(target)


def _headline(base: int, tdee: int, target: int, goal: str) -> str:
    label = _GOAL_LABELS.get(goal, "Поддержание")
    return (
        f"BMR: <b>{base} ккал</b>. Полная норма (TDEE): <b>{tdee} ккал</b>."
        f"\nЦель — {label}: <b>{target} ккал/день</b>."
    )


def _bullets(goal: str) -> list[str]:
    goals = {
        "loss": "Дефицит 10–15%: добавь шаги, держи белок и клетчатку в каждом приёме пищи.",
        "maintain": "Фокус на регулярности сна, белок 1.6 г/кг и 7–9 часов восстановления.",
        "gain": "Слегка избыточные калории + силовые 3 раза в неделю для набора сухой массы.",
    }
    return [
        goals.get(goal, goals["maintain"]),
        "Планируй меню заранее и держи полезные перекусы под рукой.",
        "Пей 30–35 мл воды на кг веса и следи за шагами (8–10 тыс.).",
    ]


async def _finalize(
    c: CallbackQuery,
    base: int,
    tdee: int,
    target: int,
    goal: str,
) -> None:
    sess = SESSIONS.get(c.from_user.id, {})
    age = int(sess.get("age", 0))
    weight = float(sess.get("weight", 0.0))
    height = int(sess.get("height", 0))
    sex = sess.get("sex", "m")
    factor_key = sess.get("activity_key", "155")
    factor = _ACTIVITY_FACTORS.get(factor_key, ("", 1.55))[1]

    rec_codes = ["T8_BLEND", "TEO_GREEN", "VITEN"]
    cards = pick_for_context("calc_kcal", goal, rec_codes)
    bullets = _bullets(goal)

    plan_payload = {
        "title": "План: калории (BMR/TDEE)",
        "context": "calc_kcal",
        "context_name": "Калькулятор калорий",
        "level": goal,
        "products": rec_codes,
        "lines": [
            f"— BMR: {base} ккал",
            f"— TDEE: {tdee} ккал",
            f"— Целевые калории: {target} ккал",
        ],
        "actions": bullets,
        "notes": "Настрой рацион вместе с врачом/коучем при хронических состояниях.",
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
                "calc": "kcal",
                "base": base,
                "tdee": tdee,
                "target": target,
                "goal": goal,
                "factor": factor,
                "age": age,
                "weight": weight,
                "height": height,
                "sex": sex,
            },
        )
        await calc_unified.save_result(
            session,
            c.from_user.id,
            "kcal",
            {
                "base": base,
                "tdee": tdee,
                "target": target,
                "goal": goal,
                "factor": factor,
                "age": age,
                "weight": weight,
                "height": height,
                "sex": sex,
            },
        )
        await commit_safely(session)

    await send_product_cards(
        c,
        "Итог: дневная норма калорий",
        cards,
        headline=_headline(base, tdee, target, goal),
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(c.from_user.id, None)


@router.callback_query(F.data.startswith("calc:kcal:sex:"))
async def choose_sex(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "kcal":
        await c.answer()
        return

    sex = c.data.split(":")[-1]
    if sex not in {"m", "f"}:
        await c.answer()
        return

    sess["sex"] = sex
    sess["step"] = "age"
    await c.answer()
    await c.message.edit_text(
        "Укажи возраст (полных лет):",
        reply_markup=kb_back_home("calc:menu"),
    )


@router.callback_query(F.data.startswith("calc:kcal:activity:"))
async def choose_activity(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "kcal":
        await c.answer()
        return

    key = c.data.split(":")[-1]
    if key not in _ACTIVITY_FACTORS:
        await c.answer()
        return

    sess["activity_key"] = key
    sess["step"] = "goal"
    await c.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="Снижение веса", callback_data="calc:kcal:goal:loss")
    kb.button(text="Поддержание", callback_data="calc:kcal:goal:maintain")
    kb.button(text="Набор массы", callback_data="calc:kcal:goal:gain")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2, 1, 2)
    await c.message.answer(
        "Какая цель?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("calc:kcal:goal:"))
async def choose_goal(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "kcal":
        await c.answer()
        return

    goal = c.data.split(":")[-1]
    if goal not in _GOAL_LABELS:
        await c.answer()
        return

    try:
        sex = sess["sex"]
        age = int(sess["age"])
        weight = float(sess["weight"])
        height = int(sess["height"])
        factor_key = sess.get("activity_key", "155")
        factor = _ACTIVITY_FACTORS.get(factor_key, ("", 1.55))[1]
    except (KeyError, ValueError):
        await c.answer()
        await c.message.answer(
            "Данные неполные. Запусти расчёт заново.",
            reply_markup=kb_back_home("calc:menu"),
        )
        SESSIONS.pop(c.from_user.id, None)
        return

    base, tdee, target = _compute(sex, age, weight, height, factor, goal)  # type: ignore[arg-type]
    await _finalize(c, base, tdee, target, goal)


__all__ = ["router", "handle_message"]
