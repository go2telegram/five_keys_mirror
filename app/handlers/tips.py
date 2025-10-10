from __future__ import annotations

import datetime as dt
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.repo import events as events_repo, retention as retention_repo
from app.retention import journeys as journeys_logic, tips as tips_logic
from app.services import retention_messages
from app.storage import commit_safely

router = Router(name="tips")


def _parse_time_argument(raw: str | None) -> dt.time | None:
    if not raw:
        return None
    normalized = raw.strip().lower()
    if normalized.startswith("set"):
        normalized = normalized[3:].strip()
    matches = list(re.finditer(r"(\d{1,2})[:\.]?(\d{2})", normalized))
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
            "Управление подпиской: /tips on, /tips off, /tips_time set 10:00",
        )
        return

    async with compat_session(session_scope) as session:
        setting = await retention_repo.get_or_create_settings(session, message.from_user.id)
        tip = await retention_repo.pick_tip(session, exclude_id=setting.last_tip_id)
        if tip is None:
            await message.answer("Пока нет советов, попробуй позже.")
            return
        text = tips_logic.clean_tip_text(tip.text)
        markup = tips_logic.tip_keyboard(tip.id)
        await message.answer(text, reply_markup=markup)
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
            await events_repo.log(session, message.from_user.id, "daily_tip_on", {})
            await commit_safely(session)
            await message.answer("🔔 Советы включены. Следующий придёт в привычное время.")
            return
        if action.startswith("off"):
            await retention_repo.set_tips_enabled(session, message.from_user.id, False)
            await events_repo.log(session, message.from_user.id, "daily_tip_off", {})
            await commit_safely(session)
            await message.answer("🔕 Советы выключены. Включить снова: /tips on")
            return

        await message.answer(tips_logic.describe_setting(setting))


@router.message(Command("tips_time"))
async def tips_time(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    desired = _parse_time_argument(command.args)
    if desired is None:
        await message.answer("Формат: /tips_time set 09:30")
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
    await message.answer(
        f"Время советов обновлено: {desired.strftime('%H:%M')} (по твоему часовому поясу)."
    )


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


@router.callback_query(F.data == "tips:disable")
async def tips_disable(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    async with compat_session(session_scope) as session:
        await retention_repo.set_tips_enabled(session, callback.from_user.id, False)
        await events_repo.log(
            session,
            callback.from_user.id,
            "daily_tip_off",
            {"source": "inline"},
        )
        await commit_safely(session)
    await callback.answer("Советы выключены")
    await callback.message.answer("🔕 Советы выключены. Включить снова: /tips on")


@router.callback_query(F.data == journeys_logic.SLEEP_CTA_CALLBACK)
async def journey_tracker_sleep(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer("Напоминаем про трекер сна")
    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            callback.from_user.id,
            journeys_logic.JOURNEY_CTA_EVENTS[journeys_logic.SLEEP_JOURNEY],
            {},
        )
        await commit_safely(session)
    await callback.message.answer(journeys_logic.format_cta_reply(journeys_logic.SLEEP_JOURNEY))


@router.callback_query(F.data == journeys_logic.STRESS_CTA_CALLBACK)
async def journey_premium_plan(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer("Открываем Премиум")
    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            callback.from_user.id,
            journeys_logic.JOURNEY_CTA_EVENTS[journeys_logic.STRESS_JOURNEY],
            {},
        )
        await commit_safely(session)
    await callback.message.answer(journeys_logic.format_cta_reply(journeys_logic.STRESS_JOURNEY))
