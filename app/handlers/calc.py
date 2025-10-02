import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.catalog.api import product_meta
from app.config import settings
from app.db.session import session_scope
from app.handlers.quiz_common import send_product_cards
from app.keyboards import kb_back_home, kb_calc_menu
from app.reco import CTX, product_lines
from app.repo import events as events_repo, users as users_repo
from app.storage import SESSIONS, set_last_plan

router = Router()

# --- Наборы рекомендаций под калькуляторы ---


def msd_recommendations():
    """
    Идеальный вес (MSD): метаболизм + микробиом.
    """
    return ["OMEGA3", "TEO_GREEN"]


def bmi_recommendations(bmi: float):
    """
    Возвращает (коды продуктов, контекст для карточки).
    """
    if bmi < 18.5:
        return ["TEO_GREEN", "OMEGA3"], "bmi_deficit"
    elif bmi < 25:
        return ["T8_BLEND", "VITEN"], "bmi_norm"
    elif bmi < 30:
        return ["TEO_GREEN", "T8_EXTRA"], "bmi_over"
    else:
        return ["T8_EXTRA", "TEO_GREEN"], "bmi_obese"


def _cards_with_overrides(codes: list[str], context_key: str) -> list[dict]:
    overrides = CTX.get(context_key, {})
    cards: list[dict] = []
    for code in codes:
        meta = product_meta(code)
        if not meta:
            continue
        cards.append(
            {
                "code": meta["code"],
                "name": meta.get("name", meta["code"]),
                "short": meta.get("short", ""),
                "props": meta.get("props", []),
                "images": meta.get("images", []),
                "order_url": meta.get("order_url"),
                "helps_text": overrides.get(code),
            }
        )
    return cards


# --- Меню ---


@router.callback_query(F.data == "calc:menu")
async def calc_menu(c: CallbackQuery):
    await c.answer()
    await c.message.edit_text("Выбери калькулятор:", reply_markup=kb_calc_menu())


# --- MSD (идеальный вес по росту) ---


@router.callback_query(F.data == "calc:msd")
async def calc_msd(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"calc": "msd"}
    await c.answer()
    await c.message.edit_text(
        "Введи рост в сантиметрах и пол (М/Ж), например: <code>165 Ж</code>",
        reply_markup=kb_back_home("calc:menu"),
    )


@router.message(F.text.regexp(r"^\s*\d{2,3}\s*[МмЖж]\s*$"))
async def handle_msd(m: Message):
    sess = SESSIONS.get(m.from_user.id, {})
    if sess.get("calc") != "msd":
        return

    h_cm, sex = re.findall(r"(\d{2,3})\s*([МмЖж])", m.text.strip())[0]
    h = int(h_cm) / 100.0
    k = 23.0 if sex.lower().startswith("м") else 21.5
    ideal = round(h * h * k, 1)

    rec_codes = msd_recommendations()
    cards = _cards_with_overrides(rec_codes, "msd")
    lines = product_lines(rec_codes, "msd")
    bullets = [
        "Белок в каждом приёме пищи (1.2–1.6 г/кг).",
        "Ежедневная клетчатка (TEO GREEN) + вода 30–35 мл/кг.",
        "30 минут ходьбы + 2 силовые тренировки в неделю.",
    ]
    notes = "Цель — баланс мышц и жира. Делай замеры раз в 2 недели."

    # для PDF
    plan_payload = {
        "title": "План: Идеальный вес (MSD)",
        "context": "msd",
        "context_name": "Калькулятор MSD",
        "level": None,
        "products": rec_codes,
        "lines": lines,
        "actions": bullets,
        "notes": notes,
        "order_url": settings.velavie_url,
    }

    async with session_scope() as session:
        await users_repo.get_or_create_user(session, m.from_user.id, m.from_user.username)
        await set_last_plan(session, m.from_user.id, plan_payload)
        await events_repo.log(
            session,
            m.from_user.id,
            "calc_finish",
            {"calc": "msd", "ideal_weight": ideal},
        )
        await session.commit()

    headline = (
        f"Ориентир по формуле MSD: <b>{ideal} кг</b>." "\nФормула — это ориентир. Фокус на составе тела (мышцы ≠ жир)."
    )
    await send_product_cards(
        m,
        "Итог: идеальный вес по MSD",
        cards,
        headline=headline,
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(m.from_user.id, None)


# --- ИМТ (индекс массы тела) ---


@router.callback_query(F.data == "calc:bmi")
async def calc_bmi(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"calc": "bmi"}
    await c.answer()
    await c.message.edit_text(
        "Введи рост и вес, например: <code>183 95</code>",
        reply_markup=kb_back_home("calc:menu"),
    )


@router.message(F.text.regexp(r"^\s*\d{2,3}\s+\d{2,3}(\.\d+)?\s*$"))
async def handle_bmi(m: Message):
    sess = SESSIONS.get(m.from_user.id, {})
    if sess.get("calc") != "bmi":
        return

    nums = re.findall(r"\d+(?:\.\d+)?", m.text)
    h_cm = float(nums[0])
    w = float(nums[1])
    h = h_cm / 100.0
    bmi = round(w / (h * h), 1)

    # категория
    if bmi < 18.5:
        cat, hint = "дефицит", "Набираем «правильный» вес: белок, клетчатка, мягкая коррекция ЖКТ."
    elif bmi < 25:
        cat, hint = "норма", "Поддерживаем энергию и иммунитет."
    elif bmi < 30:
        cat, hint = "избыток", "Фокус на микробиом и митохондрии для устойчивого снижения массы."
    else:
        cat, hint = "ожирение", "Системно: микробиом + митохондрии + режим сна/движения."

    rec_codes, ctx = bmi_recommendations(bmi)
    cards = _cards_with_overrides(rec_codes, ctx)

    lines = product_lines(rec_codes, ctx)
    bullets = [
        "Сон 7–9 часов, ужин за 3 часа до сна.",
        "10 минут утреннего света, 30 минут ходьбы ежедневно.",
        "Клетчатка + белок в каждом приёме пищи.",
    ]
    notes = "Если есть ЖКТ-жалобы — начни с TEO GREEN + MOBIO и режима питания."

    plan_payload = {
        "title": "План: Индекс массы тела (ИМТ)",
        "context": "bmi",
        "context_name": "Калькулятор ИМТ",
        "level": cat,
        "products": rec_codes,
        "lines": lines,
        "actions": bullets,
        "notes": notes,
        "order_url": settings.velavie_url,
    }

    async with session_scope() as session:
        await users_repo.get_or_create_user(session, m.from_user.id, m.from_user.username)
        await set_last_plan(session, m.from_user.id, plan_payload)
        await events_repo.log(
            session,
            m.from_user.id,
            "calc_finish",
            {"calc": "bmi", "bmi": bmi, "category": cat},
        )
        await session.commit()

    headline = (
        f"ИМТ: <b>{bmi}</b> — {cat}."
        "\nИМТ оценивает соотношение роста и веса, но не показывает состав тела."
        f"\n{hint}"
    )
    await send_product_cards(
        m,
        "Итог: индекс массы тела",
        cards,
        headline=headline,
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(m.from_user.id, None)
