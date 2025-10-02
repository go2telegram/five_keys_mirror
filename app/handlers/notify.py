"""Notification preferences handlers."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import session_scope
from app.keyboards import kb_back_home
from app.repo import events as events_repo

router = Router(name="notify")
LOG = logging.getLogger(__name__)


def _status_keyboard(enabled: bool):
    kb = InlineKeyboardBuilder()
    if enabled:
        kb.button(text="🔕 Выключить", callback_data="notify:off")
    else:
        kb.button(text="🔔 Включить", callback_data="notify:on")
    for row in kb_back_home("notify:help").inline_keyboard:
        kb.row(*row)
    return kb.as_markup()


async def _set_event(user_id: int, event_name: str) -> None:
    async with session_scope() as session:
        await events_repo.log(session, user_id, event_name, {})
        await session.commit()


async def _is_enabled(user_id: int) -> bool:
    async with session_scope() as session:
        last_on = await events_repo.last_by(session, user_id, "notify_on")
        last_off = await events_repo.last_by(session, user_id, "notify_off")
    return bool(last_on and (not last_off or last_on.ts > last_off.ts))


async def _render(message: Message | CallbackQuery, enabled: bool) -> None:
    status = "включены" if enabled else "выключены"
    text = f"Сейчас напоминания {status}.\n\n" "Используйте кнопки ниже, чтобы переключить статус."
    markup = _status_keyboard(enabled)
    if isinstance(message, CallbackQuery):
        try:
            await message.message.edit_text(text, reply_markup=markup)
        except Exception:  # noqa: BLE001 - graceful fallback with navigation buttons
            LOG.exception("notify edit failed")
            await message.message.answer(text, reply_markup=markup)
        return

    await message.answer(text, reply_markup=markup)


@router.message(Command("notify_on"))
async def notify_on_cmd(message: Message) -> None:
    await _set_event(message.from_user.id, "notify_on")
    await message.answer(
        "🔔 Напоминания включены. Буду присылать 1–2 раза в неделю.",
        reply_markup=_status_keyboard(True),
    )


@router.message(Command("notify_off"))
async def notify_off_cmd(message: Message) -> None:
    await _set_event(message.from_user.id, "notify_off")
    await message.answer(
        "🔕 Напоминания выключены. Включить снова: /notify_on",
        reply_markup=_status_keyboard(False),
    )


@router.message(Command("notify"))
async def notify_status_cmd(message: Message) -> None:
    enabled = await _is_enabled(message.from_user.id)
    await _render(message, enabled)


@router.callback_query(F.data == "notify:help")
async def notify_status_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    enabled = await _is_enabled(callback.from_user.id)
    await _render(callback, enabled)


@router.callback_query(F.data == "notify:on")
async def notify_on_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await _set_event(callback.from_user.id, "notify_on")
    await _render(callback, True)


@router.callback_query(F.data == "notify:off")
async def notify_off_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await _set_event(callback.from_user.id, "notify_off")
    await _render(callback, False)
