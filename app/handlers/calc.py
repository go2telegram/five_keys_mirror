import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.catalog.api import product_meta
from app.config import settings
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import send_product_cards
from app.keyboards import kb_back_home, kb_calc_menu
from app.reco import CTX, personalize_codes, product_lines
from app.repo import events as events_repo, profiles as profiles_repo, users as users_repo
from app.storage import SESSIONS, commit_safely, set_last_plan

router = Router()

MSD_INPUT_RE = re.compile(r"^\s*(?P<height>\d{2,3})\s*(?P<sex>[МмЖж])\s*$")

MSD_PROMPT = "Не удалось распознать ввод. Пример: <code>165 Ж</code>." "\nУкажи рост в сантиметрах и пол (М/Ж)."

# --- Наборы рекомендаций под калькуляторы ---


def msd_recommendations():
    """
    Идеальный вес (MSD): метаболизм + микробиом.
    """
    return ["OMEGA3", "TEO_GREEN"]


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


async def _process_msd(message: Message) -> None:
    text = (message.text or "").strip()
    match = MSD_INPUT_RE.fullmatch(text)
    if not match:
        await message.answer(MSD_PROMPT, reply_markup=kb_back_home("calc:menu"))
        return

    height_cm = int(match.group("height"))
    sex = match.group("sex")
    height_m = height_cm / 100.0
    coeff = 23.0 if sex.lower().startswith("м") else 21.5
    ideal = round(height_m * height_m * coeff, 1)

    rec_codes = msd_recommendations()
    bullets = [
        "Белок в каждом приёме пищи (1.2–1.6 г/кг).",
        "Ежедневная клетчатка (TEO GREEN) + вода 30–35 мл/кг.",
        "30 минут ходьбы + 2 силовые тренировки в неделю.",
    ]
    notes = "Цель — баланс мышц и жира. Делай замеры раз в 2 недели."

    personalized_codes: list[str]
    lines: list[str]

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, message.from_user.id, message.from_user.username)
        profile_data = await profiles_repo.get_profile_data(session, message.from_user.id)
        personalized_codes = personalize_codes(rec_codes, profile_data)
        if not personalized_codes:
            personalized_codes = rec_codes
        lines = product_lines(personalized_codes, "msd")
        plan_payload = {
            "title": "План: Идеальный вес (MSD)",
            "context": "msd",
            "context_name": "Калькулятор MSD",
            "level": None,
            "products": personalized_codes,
            "lines": lines,
            "actions": bullets,
            "notes": notes,
            "order_url": settings.velavie_url,
        }
        await set_last_plan(session, message.from_user.id, plan_payload)
        await events_repo.log(
            session,
            message.from_user.id,
            "calc_finish",
            {"calc": "msd", "ideal_weight": ideal},
        )
        await commit_safely(session)

    headline = (
        f"Ориентир по формуле MSD: <b>{ideal} кг</b>." "\nФормула — это ориентир. Фокус на составе тела (мышцы ≠ жир)."
    )
    cards = _cards_with_overrides(personalized_codes, "msd")
    await send_product_cards(
        message,
        "Итог: идеальный вес по MSD",
        cards,
        headline=headline,
        bullets=bullets,
        back_cb="calc:menu",
    )
    SESSIONS.pop(message.from_user.id, None)


@router.message(F.text)
async def handle_calc_message(message: Message):
    sess = SESSIONS.get(message.from_user.id)
    if not sess:
        return

    if sess.get("calc_engine") == "core":
        return

    calc_kind = sess.get("calc")
    if calc_kind == "msd":
        await _process_msd(message)
