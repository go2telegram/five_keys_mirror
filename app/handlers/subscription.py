from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timezone

from app.config import settings
from app.storage import USERS
from app.tracking import track

router = Router()


def _now():
    return datetime.now(timezone.utc)


def _has_active_sub(user_id: int) -> tuple[bool, str]:
    sub = USERS.get(user_id, {}).get("subscription")
    if not sub:
        return False, ""
    until = datetime.fromisoformat(sub["until"])
    return (until > _now(), sub["plan"])


def _kb_sub_menu():
    kb = InlineKeyboardBuilder()
    if settings.TRIBUTE_LINK_BASIC:
        kb.button(
            text=f"💎 MITO Basic — {settings.SUB_BASIC_PRICE}", url=settings.TRIBUTE_LINK_BASIC)
    if settings.TRIBUTE_LINK_PRO:
        kb.button(
            text=f"💎 MITO Pro — {settings.SUB_PRO_PRICE}", url=settings.TRIBUTE_LINK_PRO)
    kb.button(text="🔁 Проверить подписку", callback_data="sub:check")
    kb.button(text="🔓 Открыть Premium", callback_data="premium:menu")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


@router.callback_query(F.data == "sub:menu")
async def sub_menu(c: CallbackQuery):
    await track("purchase_attempt", c.from_user.id)
    await c.message.edit_text(
        "💎 <b>Подписка</b>\nОформите доступ и получите Premium-разделы МИТОсообщества.",
        reply_markup=_kb_sub_menu()
    )


@router.callback_query(F.data == "sub:check")
async def sub_check(c: CallbackQuery):
    ok, plan = _has_active_sub(c.from_user.id)
    if ok:
        await c.message.edit_text(f"✅ Подписка активна: <b>{plan.upper()}</b>")
    else:
        await c.message.edit_text(
            "Пока подписка не найдена. Завершите оплату в Tribute и дождитесь подтверждения (вебхук).",
            reply_markup=_kb_sub_menu()
        )
