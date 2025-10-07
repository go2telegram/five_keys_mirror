"""Water balance calculator flow."""

from __future__ import annotations

from typing import Literal

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.api import pick_for_context
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import send_product_cards
from app.keyboards import kb_back_home
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router(name="calc_water")

_ACTIVITY_LABELS: dict[str, str] = {
    "low": "Низкая активность",
    "moderate": "Умеренная активность",
    "high": "Высокая активность",
}

_CLIMATE_LABELS: dict[str, str] = {
    "temperate": "Умеренный климат",
    "hot": "Жаркий климат",
}


def _activity_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code in ("low", "moderate", "high"):
        kb.button(text=_ACTIVITY_LABELS[code], callback_data=f"calc:water:activity:{code}")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 2)
    return kb


def _climate_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for code in ("temperate", "hot"):
        kb.button(text=_CLIMATE_LABELS[code], callback_data=f"calc:water:climate:{code}")
    kb.button(text="⬅️ Назад", callback_data="calc:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 2)
    return kb


@router.callback_query(F.data == "calc:water")
async def start_water_calc(c: CallbackQuery) -> None:
    SESSIONS[c.from_user.id] = {"calc": "water", "step": "weight"}
    await c.answer()
    await c.message.edit_text(
        "Введи вес в килограммах, например: <code>72</code>",
        reply_markup=kb_back_home("calc:menu"),
    )


async def handle_message(message: Message) -> bool:
    sess = SESSIONS.get(message.from_user.id)
    if not sess or sess.get("calc") != "water":
        return False

    step = sess.get("step")
    if step != "weight":
        return True

    text = (message.text or "").replace(",", ".").strip()
    try:
        weight = float(text)
    except ValueError:
        weight = 0.0

    if weight <= 0 or weight > 300:
        await message.answer(
            "Не удалось распознать вес. Пример: <code>72.5</code>",
            reply_markup=kb_back_home("calc:menu"),
        )
        return True

    sess["weight"] = weight
    sess["step"] = "activity"
    kb = _activity_keyboard()
    await message.answer(
        "Выбери уровень активности:",
        reply_markup=kb.as_markup(),
    )
    return True


def _compute_total(
    weight: float,
    activity: Literal["low", "moderate", "high"],
    climate: Literal["temperate", "hot"],
) -> tuple[float, int]:
    base = weight * 0.03
    activity_add = {"low": 0.0, "moderate": 0.35, "high": 0.6}[activity]
    climate_add = {"temperate": 0.0, "hot": 0.7}[climate]
    total = round(base + activity_add + climate_add, 1)
    glasses = max(1, round(total / 0.25))
    return total, glasses


def _headline(total: float, glasses: int) -> str:
    return f"Рекомендуемая дневная норма: <b>{total} л</b>" f" (~{glasses} стаканов по 250 мл)."


def _bullets(activity: str, climate: str) -> list[str]:
    hints = {
        "low": "Добавь короткую разминку днём и шаги к вечеру.",
        "moderate": "Держи бутылку воды под рукой и пей по глотку каждый час.",
        "high": "Пополняй воду до и после тренировок, добавь электролиты.",
    }
    climate_hint = {
        "temperate": "Стартуй утро со стакана воды натощак.",
        "hot": "В жару добавляй щепотку соли/лимон к одному-двум стаканам.",
    }
    return [
        "Отслеживай количество через приложение или бутылку с делениями.",
        hints.get(activity, "Поддерживай ровный водный режим днём."),
        climate_hint.get(climate, "Пей по 2-3 больших стакана между приёмами пищи."),
    ]


async def _finalize(c: CallbackQuery, total: float, glasses: int) -> None:
    user_id = c.from_user.id
    sess = SESSIONS.get(user_id, {})
    weight = float(sess.get("weight", 0.0))
    activity = sess.get("activity", "moderate")
    climate = sess.get("climate", "temperate")

    rec_codes = ["TEO_GREEN", "OMEGA3"]
    cards = pick_for_context("calc_water", None, rec_codes)
    bullets = _bullets(activity, climate)

    plan_payload = {
        "title": "План: водный баланс",
        "context": "calc_water",
        "context_name": "Калькулятор водного баланса",
        "level": None,
        "products": rec_codes,
        "lines": [
            f"— Пить {total} л воды в день (~{glasses} стаканов)",
            "— Обновлять бутылку каждые 2–3 часа",
        ],
        "actions": bullets,
        "notes": ("Следи за самочувствием и корректируй норму с врачом при хронических состояниях."),
        "order_url": settings.velavie_url,
    }

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id, c.from_user.username)
        await set_last_plan(session, user_id, plan_payload)
        await events_repo.log(
            session,
            user_id,
            "calc_finish",
            {
                "calc": "water",
                "liters": total,
                "glasses": glasses,
                "activity": activity,
                "climate": climate,
                "weight": weight,
            },
        )
        await commit_safely(session)

    await send_product_cards(
        c,
        "Итог: водный баланс",
        cards,
        headline=_headline(total, glasses),
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(user_id, None)


@router.callback_query(F.data.startswith("calc:water:activity:"))
async def choose_activity(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "water":
        await c.answer()
        return

    activity = c.data.split(":")[-1]
    if activity not in _ACTIVITY_LABELS:
        await c.answer()
        return

    sess["activity"] = activity
    sess["step"] = "climate"
    await c.answer()
    await c.message.answer(
        "Выбери климат:",
        reply_markup=_climate_keyboard().as_markup(),
    )


@router.callback_query(F.data.startswith("calc:water:climate:"))
async def choose_climate(c: CallbackQuery) -> None:
    sess = SESSIONS.get(c.from_user.id)
    if not sess or sess.get("calc") != "water":
        await c.answer()
        return

    climate = c.data.split(":")[-1]
    if climate not in _CLIMATE_LABELS:
        await c.answer()
        return

    weight = float(sess.get("weight") or 0.0)
    activity = sess.get("activity", "moderate")
    sess["climate"] = climate
    if weight <= 0:
        await c.answer()
        await c.message.answer(
            "Вес не указан. Запусти расчёт заново.",
            reply_markup=kb_back_home("calc:menu"),
        )
        SESSIONS.pop(c.from_user.id, None)
        return

    total, glasses = _compute_total(weight, activity, climate)  # type: ignore[arg-type]
    await _finalize(c, total, glasses)


__all__ = ["router", "handle_message"]
