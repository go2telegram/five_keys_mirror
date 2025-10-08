"""Profile section handlers."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import (
    events as events_repo,
    referrals as referrals_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)

router = Router(name="profile")


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        tz = ZoneInfo(settings.TIMEZONE) if settings.TIMEZONE else ZoneInfo("UTC")
    except Exception:  # pragma: no cover - fallback if tzdata missing
        tz = ZoneInfo("UTC")
    return value.astimezone(tz).strftime("%d.%m.%Y")


async def _notifications_enabled(session, user_id: int) -> bool:
    last_on = await events_repo.last_by(session, user_id, "notify_on")
    last_off = await events_repo.last_by(session, user_id, "notify_off")
    return bool(last_on and (not last_off or last_on.ts > last_off.ts))


def _profile_keyboard(notify_enabled: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if notify_enabled:
        kb.button(text="🔕 Выключить напоминания", callback_data="notify:off")
    else:
        kb.button(text="🔔 Включить напоминания", callback_data="notify:on")
    for row in kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb


def _plan_lines(events) -> list[str]:
    if not events:
        return ["• Планов пока нет — пройди тест или калькулятор."]

    lines: list[str] = []
    for event in events:
        meta = event.meta or {}
        title = meta.get("title") or meta.get("context_name") or meta.get("context") or "Персональный план"
        ts = _format_date(event.ts)
        lines.append(f"• {title} ({ts})")
    return lines


async def _profile_payload(user_id: int, username: str | None):
    async with compat_session(session_scope) as session:
        user = await users_repo.get_or_create_user(session, user_id, username)
        is_active, subscription = await subscriptions_repo.is_active(session, user.id)
        invited, converted = await referrals_repo.stats_for_referrer(session, user.id)
        plans = await events_repo.recent_plans(session, user.id, limit=3)
        notify_enabled = await _notifications_enabled(session, user.id)

    username_text = f"@{user.username}" if user.username else "—"
    sub_status = "Активна" if is_active and subscription else "Не найдена"
    until_str = _format_date(subscription.until if subscription else None)
    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"ID: <code>{user.id}</code>",
        f"Username: {username_text}",
        "",
        "💎 Подписка:",
        f"• Статус: {sub_status}",
        f"• План: {subscription.plan.upper() if subscription else '—'}",
        f"• Оплачено до: {until_str}",
        "",
        "📊 Реферальная программа:",
        f"• Приглашено: {invited}",
        f"• Конвертировались: {converted}",
        "",
        "🗂 Последние планы:",
    ]
    lines.extend(_plan_lines(plans))
    lines.extend(
        [
            "",
            "🔔 Напоминания:",
            "• Включены" if notify_enabled else "• Выключены",
        ]
    )
    return "\n".join(lines), _profile_keyboard(notify_enabled).as_markup()


@router.callback_query(F.data == "profile:open")
async def profile_open(c: CallbackQuery) -> None:
    await c.answer()
    if c.message is None:
        return
    text, markup = await _profile_payload(c.from_user.id, c.from_user.username)
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001 - graceful fallback if edit fails
        await c.message.answer(text, reply_markup=markup)


@router.message(Command("profile"))
async def profile_command(message: Message) -> None:
    text, markup = await _profile_payload(message.from_user.id, message.from_user.username)
    await message.answer(text, reply_markup=markup)
