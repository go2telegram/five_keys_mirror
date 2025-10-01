from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import session_scope
from app.repo import subscriptions as subscriptions_repo, users as users_repo

router = Router()


def _kb_sub_menu():
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
    kb.button(text="🔁 Проверить подписку", callback_data="sub:check")
    kb.button(text="🔓 Открыть Premium", callback_data="premium:menu")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "sub:menu")
async def sub_menu(c: CallbackQuery):
    await c.message.edit_text(
        "💎 <b>Подписка</b>\nОформите доступ и получите Premium-разделы МИТОсообщества.",
        reply_markup=_kb_sub_menu(),
    )


@router.callback_query(F.data == "sub:check")
async def sub_check(c: CallbackQuery):
    async with session_scope() as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)

    if is_active and sub:
        await c.message.edit_text(f"✅ Подписка активна: <b>{sub.plan.upper()}</b>")
    else:
        await c.message.edit_text(
            "Пока подписка не найдена. Завершите оплату в Tribute и дождитесь подтверждения (вебхук).",
            reply_markup=_kb_sub_menu(),
        )
