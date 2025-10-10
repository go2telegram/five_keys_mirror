"""Router that selects a handler based on the detected user intent."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.config import settings
from app.handlers import lead as lead_handler
from app.handlers import report as report_handler
from app.keyboards import kb_goal_menu, kb_main
from app.storage import SESSIONS
from nlp.intents import Intent, IntentClassifier, IntentStatistics

router = Router(name="intent_router")
_classifier = IntentClassifier()
_stats = IntentStatistics()


@router.message(Command("intents"))
async def intents_admin(m: Message) -> None:
    """Show the current intent distribution to the admin."""
    if m.from_user.id != settings.ADMIN_ID:
        return

    if not settings.ENABLE_INTENT_UNDERSTANDING:
        await m.answer("Intent-модуль отключён (ENABLE_INTENT_UNDERSTANDING=false).")
        return

    total = _stats.total()
    if not total:
        await m.answer("Пока нет данных по интентам.")
        return

    lines = ["📊 Intent-распределение", f"Всего сообщений: {total}"]
    for intent, count in _stats.most_common():
        percent = count / total * 100 if total else 0
        lines.append(f"• {intent.value}: {count} ({percent:.1f}%)")
    await m.answer("\n".join(lines))


@router.message(StateFilter(None), F.text)
async def route_by_intent(m: Message, state: FSMContext) -> None:
    """Classify the incoming message and trigger the matching flow."""
    if not settings.ENABLE_INTENT_UNDERSTANDING:
        return

    user = m.from_user
    if user and SESSIONS.was_recently_active(user.id):
        # Another router has just processed the message (e.g. calculator
        # flows that rely on SESSIONS). Avoid sending a duplicate reply.
        return

    text = m.text or ""
    if not text.strip():
        return
    if text.startswith("/"):
        # пусть останется стандартная обработка команд
        return

    prediction = _classifier.classify(text)
    intent = prediction.intent
    if intent == Intent.ADMIN and m.from_user.id != settings.ADMIN_ID:
        intent = Intent.LEARN

    _stats.add(intent)

    if intent == Intent.SUPPORT:
        await lead_handler.lead_cmd(m, state)
        return

    if intent == Intent.BUY:
        await m.answer(
            "Подберу продукты под твою задачу. Выбери цель:",
            reply_markup=kb_goal_menu(),
        )
        return

    if intent == Intent.REPORT:
        await report_handler.pdf_cmd(m)
        return

    if intent == Intent.ADMIN:
        total = _stats.total()
        lines = [
            "📈 Intent-диагностика",
            f"Всего классификаций: {total}",
        ]
        for det_intent, count in _stats.most_common():
            percent = count / total * 100 if total else 0
            lines.append(f"• {det_intent.value}: {count} ({percent:.1f}%)")
        await m.answer("\n".join(lines))
        return

    # default → Intent.LEARN
    await m.answer(
        "Вот что могу предложить:\n"
        "• 🧭 Навигатор — подбор материалов\n"
        "• 🗂 Квизы — оценить состояние\n"
        "• 📐 Калькуляторы — расчёты\n"
        "• 📝 Консультация — если нужен эксперт\n"
        "Выбирай раздел ниже:",
        reply_markup=kb_main(),
    )
