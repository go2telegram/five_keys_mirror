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
    await callback.message.answer(
        "Чтобы отслеживать сон, используй команду <code>/track_sleep 7</code> или поделись фактическими часами."
    )


@router.callback_query(F.data == "journey:premium_plan")
async def journey_premium_plan(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    await callback.answer("Открываем Премиум")
    async with compat_session(session_scope) as session:
        await events_repo.log(session, callback.from_user.id, "journey_premium_cta", {})
        await commit_safely(session)
    await callback.message.answer(
        "💎 Премиум даёт еженедельные планы, трекеры и поддержку. Оформить подписку можно в разделе /premium."
    )
