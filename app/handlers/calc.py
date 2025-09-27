import re
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from app.keyboards import kb_calc_menu, kb_back_home, kb_buylist_pdf
from app.storage import SESSIONS, set_last_plan
from app.utils_media import send_product_album
from app.reco import product_lines
from app.config import settings

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

# --- Меню ---


@router.callback_query(F.data == "calc:menu")
async def calc_menu(c: CallbackQuery):
    await c.message.edit_text("Выбери калькулятор:", reply_markup=kb_calc_menu())

# --- MSD (идеальный вес по росту) ---


@router.callback_query(F.data == "calc:msd")
async def calc_msd(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"calc": "msd"}
    await c.message.edit_text(
        "Введи рост в сантиметрах и пол (М/Ж), например: <code>165 Ж</code>",
        reply_markup=kb_back_home("calc:menu")
    )


@router.message(F.text.regexp(r"^\s*\d{2,3}\s*[МмЖж]\s*$"))
async def handle_msd(m: Message):
    sess = SESSIONS.get(m.from_user.id, {})
    if sess.get("calc") != "msd":
        return

    h_cm, sex = re.findall(r"(\d{2,3})\s*([МмЖж])", m.text.strip())[0]
    h = int(h_cm) / 100.0
    k = 23.0 if sex.lower().startswith("м") else 21.5
    ideal = round(h*h*k, 1)

    # рекомендации + фото
    rec_codes = msd_recommendations()
    await send_product_album(m.bot, m.chat.id, rec_codes)

    # карточка
    lines = product_lines(rec_codes, "msd")
    actions = [
        "Белок в каждом приёме пищи (1.2–1.6 г/кг).",
        "Ежедневная клетчатка (TEO GREEN) + вода 30–35 мл/кг.",
        "30 минут ходьбы в день + 2 силовые тренировки в неделю.",
    ]
    notes = "Цель — баланс мышц и жира. Делай замеры раз в 2 недели."

    # для PDF
    set_last_plan(
        m.from_user.id,
        {
            "title": "План: Идеальный вес (MSD)",
            "context": "msd",
            "context_name": "Калькулятор MSD",
            "level": None,
            "products": rec_codes,
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": settings.VILAVI_ORDER_NO_REG
        }
    )

    text = (
        f"Ориентир по формуле MSD: <b>{ideal} кг</b>.\n\n"
        "Что это значит:\n"
        "• Формула даёт <u>ориентир</u> для цели по весу.\n"
        "• Важнее не просто число, а <b>состав тела</b> (мышцы ≠ жир).\n\n"
        "Поддержка:\n" + "\n".join(lines)
    )
    await m.answer(text, reply_markup=kb_buylist_pdf("calc:menu", rec_codes))
    SESSIONS.pop(m.from_user.id, None)

# --- ИМТ (индекс массы тела) ---


@router.callback_query(F.data == "calc:bmi")
async def calc_bmi(c: CallbackQuery):
    SESSIONS[c.from_user.id] = {"calc": "bmi"}
    await c.message.edit_text(
        "Введи рост и вес, например: <code>183 95</code>",
        reply_markup=kb_back_home("calc:menu")
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
    bmi = round(w / (h*h), 1)

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
    await send_product_album(m.bot, m.chat.id, rec_codes)

    lines = product_lines(rec_codes, ctx)
    actions = [
        "Сон 7–9 часов, ужин за 3 часа до сна.",
        "10 минут утреннего света, 30 минут ходьбы ежедневно.",
        "Клетчатка + белок в каждом приёме пищи.",
    ]
    notes = "Если есть ЖКТ-жалобы — начни с TEO GREEN + MOBIO и режима питания."

    set_last_plan(
        m.from_user.id,
        {
            "title": "План: Индекс массы тела (ИМТ)",
            "context": "bmi",
            "context_name": "Калькулятор ИМТ",
            "level": cat,
            "products": rec_codes,
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": settings.VILAVI_ORDER_NO_REG
        }
    )

    text = (
        f"ИМТ: <b>{bmi}</b> — {cat}.\n\n"
        "Что такое ИМТ:\n"
        "• Индекс массы тела оценивает соотношение веса и роста.\n"
        "• Это <u>не</u> показывает состав тела (мышцы/жир), но даёт общий ориентир по рискам.\n\n"
        f"{hint}\n\n"
        "Поддержка:\n" + "\n".join(lines)
    )
    await m.answer(text, reply_markup=kb_buylist_pdf("calc:menu", rec_codes))
    SESSIONS.pop(m.from_user.id, None)
