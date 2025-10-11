from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import events as events_repo, subscriptions as subscriptions_repo, users as users_repo
from app.storage import commit_safely
from app.utils import safe_edit_text

router = Router(name="subscription")


def _kb_sub_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Проверить статус", callback_data="sub:check")
    if settings.TRIBUTE_LINK_BASIC:
        kb.button(
            text=f"💎 MITO Basic — {settings.SUB_BASIC_PRICE}",
            url=settings.TRIBUTE_LINK_BASIC,
        )
    if settings.TRIBUTE_LINK_PRO:
        kb.button(
            text=f"💎 MITO Pro — {settings.SUB_PRO_PRICE}",
            url=settings.TRIBUTE_LINK_PRO,
        )
    kb.button(text="ℹ️ Как продлить", callback_data="sub:renew")
    kb.adjust(1)
    markup = kb.as_markup()
    markup.inline_keyboard.extend(kb_back_home("home:main").inline_keyboard)
    return markup


def _kb_sub_renew() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.TRIBUTE_LINK_BASIC:
        kb.button(
            text=f"💎 MITO Basic — {settings.SUB_BASIC_PRICE}",
            url=settings.TRIBUTE_LINK_BASIC,
        )
    if settings.TRIBUTE_LINK_PRO:
        kb.button(
            text=f"💎 MITO Pro — {settings.SUB_PRO_PRICE}",
            url=settings.TRIBUTE_LINK_PRO,
        )
    kb.adjust(1)
    for row in kb_back_home("sub:menu").inline_keyboard:
        kb.row(*row)
    return kb.as_markup()


def _format_until(until: datetime) -> str:
    try:
        tz = ZoneInfo(settings.TIMEZONE) if settings.TIMEZONE else ZoneInfo("UTC")
    except Exception:  # pragma: no cover - fallback for invalid tz data
        tz = ZoneInfo("UTC")
    return until.astimezone(tz).strftime("%d.%m.%Y")


@router.callback_query(F.data == "sub:menu")
async def sub_menu(c: CallbackQuery):
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        await events_repo.log(session, c.from_user.id, "subscription_menu", {})
        await commit_safely(session)
    await c.answer()
    markup = _kb_sub_menu()
    await safe_edit_text(
        c.message,
        "💎 <b>Подписка</b>\nПолучите доступ к Premium и закрытым материалам.",
        markup,
    )


@router.callback_query(F.data == "sub:check")
async def sub_check(c: CallbackQuery):
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)
        plan = sub.plan if sub else None
        until = sub.until.isoformat() if sub else None
        await events_repo.log(
            session,
            c.from_user.id,
            "subscription_check",
            {"active": is_active, "plan": plan, "until": until},
        )
        await commit_safely(session)

    await c.answer()
    if is_active and sub:
        until_text = _format_until(sub.until)
        text = f"✅ <b>Подписка активна</b>\nТариф: <b>MITO {sub.plan.upper()}</b>\nДоступ до: <b>{until_text}</b>."
        builder = InlineKeyboardBuilder()
        builder.button(text="🔁 Проверить снова", callback_data="sub:check")
        builder.button(text="Открыть Premium", callback_data="premium:menu")
        for row in kb_back_home("sub:menu").inline_keyboard:
            builder.row(*row)
        await safe_edit_text(c.message, text, builder.as_markup())
    else:
        await safe_edit_text(
            c.message,
            "Подписка не найдена. Оплатите MITO в Tribute и дождитесь подтверждения вебхука.",
            _kb_sub_menu(),
        )


@router.callback_query(F.data == "sub:renew")
async def sub_renew(c: CallbackQuery):
    await c.answer()
    await safe_edit_text(
        c.message,
        "Выберите тариф MITO для продления доступа.",
        _kb_sub_renew(),
    )
