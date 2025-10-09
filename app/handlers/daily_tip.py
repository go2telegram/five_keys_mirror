from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.repo import daily_tips as daily_tips_repo, users as users_repo
from app.services.daily_tip import disable_tip_schedule, immediate_tip, schedule_next_tip
from app.storage import commit_safely
from app.utils import safe_edit_text

router = Router(name="daily_tip")


def _default_timezone() -> str:
    return settings.TIMEZONE or "UTC"


async def _load_subscription(user_id: int):
    async with compat_session(session_scope) as session:
        subscription = await daily_tips_repo.get_or_create_subscription(
            session,
            user_id,
            default_timezone=_default_timezone(),
        )
        await commit_safely(session)
    return subscription


def _format_next_send(subscription) -> str:
    if not subscription.next_send_at:
        return "—"
    try:
        zone = ZoneInfo(subscription.timezone or "UTC")
    except Exception:  # pragma: no cover - invalid tz fallback
        zone = ZoneInfo("UTC")
    local = subscription.next_send_at.astimezone(zone)
    return local.strftime("%d.%m %H:%M")


def _status_text(subscription) -> str:
    status = "Включены" if subscription.enabled else "Выключены"
    next_send = _format_next_send(subscription)
    return (
        "💡 Ежедневный совет\n"
        f"• Статус: {status}\n"
        f"• Часовой пояс: {subscription.timezone}\n"
        f"• Следующее напоминание: {next_send}\n\n"
        "Чтобы сменить часовой пояс, отправь: /daily_tip Europe/Moscow"
    )


def _status_keyboard(subscription) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if subscription.enabled:
        kb.button(text="🔕 Выключить", callback_data="daily_tip:off")
    else:
        kb.button(text="🔔 Включить", callback_data="daily_tip:on")
    kb.button(text="🌐 Сменить часовой пояс", callback_data="daily_tip:tz")
    kb.adjust(1, 1)
    return kb


def _validate_timezone(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        ZoneInfo(candidate)
    except Exception:
        return None
    return candidate


@router.message(Command("daily_tip"))
async def daily_tip_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    tz_arg = (message.text or "").split(maxsplit=1)
    tz_update = None
    if len(tz_arg) > 1:
        tz_update = _validate_timezone(tz_arg[1])
        if tz_update is None:
            await message.answer("Не удалось распознать часовой пояс. Пример: /daily_tip Europe/Moscow")
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user.id, user.username)
        subscription = await daily_tips_repo.get_or_create_subscription(
            session,
            user.id,
            default_timezone=tz_update or _default_timezone(),
        )
        if tz_update:
            subscription = await daily_tips_repo.update_timezone(session, user.id, tz_update)
        await commit_safely(session)
    await immediate_tip(message.bot, user.id)
    subscription = await _load_subscription(user.id)
    markup = _status_keyboard(subscription).as_markup()
    await message.answer(_status_text(subscription), reply_markup=markup)


@router.callback_query(F.data == "daily_tip:on")
async def daily_tip_on(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        return
    subscription = await _load_subscription(user.id)
    await schedule_next_tip(user.id, timezone=subscription.timezone)
    await callback.answer("Ежедневные советы включены")
    subscription = await _load_subscription(user.id)
    markup = _status_keyboard(subscription).as_markup()
    await safe_edit_text(callback.message, _status_text(subscription), markup)


@router.callback_query(F.data == "daily_tip:off")
async def daily_tip_off(callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        return
    await disable_tip_schedule(user.id)
    subscription = await _load_subscription(user.id)
    await callback.answer("Рассылка выключена")
    markup = _status_keyboard(subscription).as_markup()
    await safe_edit_text(callback.message, _status_text(subscription), markup)


@router.callback_query(F.data == "daily_tip:tz")
async def daily_tip_tz(callback: CallbackQuery) -> None:
    await callback.answer("Напиши: /daily_tip Europe/Moscow", show_alert=False)

