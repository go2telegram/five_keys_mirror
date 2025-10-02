from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import session_scope
from app.repo import subscriptions as subscriptions_repo, users as users_repo

router = Router(name="subscription")


def _kb_sub_menu() -> InlineKeyboardBuilder:
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
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 1, 1)
    return kb


def _format_until(until: datetime) -> str:
    try:
        tz = ZoneInfo(settings.TIMEZONE) if settings.TIMEZONE else ZoneInfo("UTC")
    except Exception:  # pragma: no cover - fallback for invalid tz data
        tz = ZoneInfo("UTC")
    return until.astimezone(tz).strftime("%d.%m.%Y")


@router.callback_query(F.data == "sub:menu")
async def sub_menu(c: CallbackQuery):
    await c.answer()
    kb = _kb_sub_menu()
    await c.message.edit_text(
        "💎 <b>Подписка</b>\nПолучите доступ к Premium и закрытым материалам.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "sub:check")
async def sub_check(c: CallbackQuery):
    async with session_scope() as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)

    await c.answer()
    if is_active and sub:
        until = _format_until(sub.until)
        text = "✅ Подписка активна.\n" f"План: <b>{sub.plan.upper()}</b>\n" f"Оплачено до: <b>{until}</b>."
        kb = InlineKeyboardBuilder()
        kb.button(text="🔁 Проверить снова", callback_data="sub:check")
        kb.button(text="🏠 Домой", callback_data="home:main")
        kb.adjust(1, 1)
        await c.message.edit_text(text, reply_markup=kb.as_markup())
    else:
        kb = _kb_sub_menu()
        await c.message.edit_text(
            "Подписка пока не найдена. Завершите оплату в Tribute и дождитесь подтверждения.",
            reply_markup=kb.as_markup(),
        )


@router.callback_query(F.data == "sub:renew")
async def sub_renew(c: CallbackQuery):
    await c.answer()
    kb = _kb_sub_menu()
    await c.message.edit_text(
        "Чтобы продлить доступ, оплатите тариф MITO в Tribute или обратитесь к куратору.",
        reply_markup=kb.as_markup(),
    )
