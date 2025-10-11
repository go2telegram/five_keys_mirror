from __future__ import annotations

import datetime as dt
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.repo import events as events_repo, retention as retention_repo
from app.services import retention_messages
from app.storage import commit_safely

router = Router(name="retention")


def _parse_time_argument(raw: str | None) -> dt.time | None:
    if not raw:
        return None
    matches = list(re.finditer(r"(\d{1,2})[:\.]?(\d{2})", raw))
    if not matches:
        return None
    hour_s, minute_s = matches[-1].groups()
    try:
        hour = int(hour_s)
        minute = int(minute_s)
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return dt.time(hour, minute)


@router.message(Command("daily_tip"))
async def daily_tip_now(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    args = (command.args or "").strip().lower()
    if args != "now":
        await message.answer(
            "Используй <code>/daily_tip now</code>, чтобы получить совет сразу.\n"
            "Управление подпиской: /tips on, /tips off, /tips_time 10:00",
        )
        return

    async with compat_session(session_scope) as session:
        setting = await retention_repo.get_or_create_settings(session, message.from_user.id)
        tip = await retention_repo.pick_tip(session, exclude_id=setting.last_tip_id)
        if tip is None:
            await message.answer("Пока нет советов, попробуй позже.")
            return
        text = retention_messages.format_tip_message(tip.text)
        kb = InlineKeyboardBuilder()
        kb.button(text="👍 Полезно", callback_data=f"tips:like:{tip.id}")
        await message.answer(text, reply_markup=kb.as_markup())
        now = dt.datetime.now(dt.timezone.utc)
        await retention_repo.update_tip_log(session, setting, tip=tip, sent_at=now)
        await events_repo.log(
            session,
            message.from_user.id,
            "daily_tip_manual",
            {"tip_id": tip.id},
        )
        await commit_safely(session)


@router.message(Command("tips"))
async def tips_toggle(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    action = (command.args or "").strip().lower()
    async with compat_session(session_scope) as session:
        setting = await retention_repo.get_or_create_settings(session, message.from_user.id)
        if action.startswith("on"):
            await retention_repo.set_tips_enabled(session, message.from_user.id, True)
            await events_repo.upsert(session, message.from_user.id, "daily_tip_on", {})
            await commit_safely(session)
            await message.answer("🔔 Советы включены. Следующий придёт в привычное время.")
            return
        if action.startswith("off"):
            await retention_repo.set_tips_enabled(session, message.from_user.id, False)
            await events_repo.upsert(session, message.from_user.id, "daily_tip_off", {})
            await commit_safely(session)
            await message.answer("🔕 Советы выключены. Включить снова: /tips on")
            return

        enabled = setting.tips_enabled
        send_time = setting.tips_time.strftime("%H:%M") if setting.tips_time else "10:00"
        await message.answer(
            "🔔 Статус советов:\n"
            f"• {'включены' if enabled else 'выключены'}\n"
            f"• время отправки: {send_time}\n\n"
            "Команды:\n/tips on — включить\n/tips off — выключить\n/tips_time 09:30 — изменить время",
        )


@router.message(Command("tips_time"))
async def tips_time(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    desired = _parse_time_argument(command.args)
    if desired is None:
        await message.answer("Формат: /tips_time 09:30")
        return

    async with compat_session(session_scope) as session:
        await retention_repo.set_tips_time(session, message.from_user.id, desired)
        await events_repo.log(
            session,
            message.from_user.id,
            "daily_tip_time_set",
            {"time": desired.strftime("%H:%M")},
        )
        await commit_safely(session)
    await message.answer(f"Время советов обновлено: {desired.strftime('%H:%M')} по твоему часовому поясу")


@router.callback_query(F.data.regexp(r"^tips:like:\d+$"))
async def tips_like(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    _, _, tip_id = callback.data.partition(":like:")
    try:
        tip_id_int = int(tip_id)
    except Exception:
        tip_id_int = None

    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            callback.from_user.id,
            "daily_tip_click",
            {"tip_id": tip_id_int},
        )
        await commit_safely(session)
    await callback.answer(retention_messages.format_tip_click_ack())


@router.callback_query(F.data == "journey:tracker_sleep")
async def journey_tracker_sleep(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer("Напоминаем про трекер сна")
    async with compat_session(session_scope) as session:
        await events_repo.log(session, callback.from_user.id, "journey_sleep_cta", {})
        await commit_safely(session)
    if callback.message:
        await callback.message.answer(
            (
                "📲 Чтобы включить трекер сна, используй команду <code>/track_sleep 7</code> "
                "или введи своё количество часов."
            )
        )


@router.callback_query(F.data == "journey:premium_plan")
async def journey_premium_plan(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer("Открываем Премиум")
    async with compat_session(session_scope) as session:
        await events_repo.log(session, callback.from_user.id, "journey_premium_cta", {})
        await commit_safely(session)
    if callback.message:
        await callback.message.answer(
            "💡 Чтобы получить Премиум-план, перейди в раздел /premium — там доступно оформление подписки."
        )


@router.callback_query(F.data.regexp(r"^journey_sleep:(excellent|ok|bad)$"))
async def journey_sleep_feedback(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    _, _, state = callback.data.partition(":") if callback.data else (None, None, None)
    responses = {
        "excellent": "Класс! Продолжаем режим: 7–8 часов, тёмная спальня, магний по необходимости.",
        "ok": "Хорошо! Для стабильности: 10 минут дневного света утром, магний/глицин вечером.",
        "bad": (
            "Окей, работаем точечно: без кофе после 14:00, 20 минут без экрана перед сном, тёплый душ. "
            "Готов прислать персональный план? /ai_plan"
        ),
    }
    reply = responses.get(state)

    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            callback.from_user.id,
            "journey_sleep_response",
            {"state": state},
        )
        await commit_safely(session)

    await callback.answer("Спасибо!")
    if reply and callback.message:
        await callback.message.answer(reply)


@router.callback_query(F.data.regexp(r"^journey_stress:(low|medium|high)$"))
async def journey_stress_feedback(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    _, _, level = callback.data.partition(":") if callback.data else (None, None, None)
    responses = {
        "low": "Отлично! Закрепим: 3×8 дыханий 1–2 раза в день.",
        "medium": "Окей. Дыхание 4-7-8, 10-мин прогулка, магний после ужина по необходимости.",
        "high": (
            "Сочувствую. Попробуй короткую релаксацию (2 минуты дыхания), снизь стимуляторы, и я соберу мягкий план. "
            "/ai_plan"
        ),
    }
    reply = responses.get(level)

    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            callback.from_user.id,
            "journey_stress_response",
            {"level": level},
        )
        await commit_safely(session)

    await callback.answer("Принято")
    if reply and callback.message:
        await callback.message.answer(reply)
