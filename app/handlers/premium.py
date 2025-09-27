from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timezone
from app.storage import USERS

router = Router()


def _active(user_id: int) -> tuple[bool, str]:
    sub = USERS.get(user_id, {}).get("subscription")
    if not sub:
        return False, ""
    return (datetime.fromisoformat(sub["until"]) > datetime.now(timezone.utc), sub["plan"])


BASIC_LINKS = [
    ("МИТОlife (новости)", "https://t.me/c/1858905974/3331"),
    ("EXTRA (полипренолы)", "https://t.me/c/1858905974/5"),
    ("VITEN (иммунитет)", "https://t.me/c/1858905974/13"),
    ("TÉO GREEN (клетчатка)", "https://t.me/c/1858905974/1205"),
    ("MOBIO (метабиотик)", "https://t.me/c/1858905974/11"),
]
PRO_LINKS = BASIC_LINKS + [
    ("Экспертные эфиры", "https://t.me/c/1858905974/459"),
    ("MITOпрограмма", "https://t.me/c/1858905974/221"),
    ("Маркетинг", "https://t.me/c/1858905974/18"),
    ("ERA Mitomatrix", "https://t.me/c/1858905974/3745"),
]


def _kb_links(pairs):
    kb = InlineKeyboardBuilder()
    for title, url in pairs:
        kb.button(text=f"🔗 {title}", url=url)
    kb.button(text="🏠 Домой", callback_data="home")
    layout = [2] * (len(pairs)//2) + ([1] if len(pairs) % 2 else []) + [1]
    kb.adjust(*layout)
    return kb.as_markup()


@router.callback_query(F.data == "premium:menu")
async def premium_menu(c: CallbackQuery):
    ok, plan = _active(c.from_user.id)
    if not ok:
        await c.message.edit_text("🔒 Premium недоступен. Оформите подписку в разделе «Подписка».")
        return
    if plan == "basic":
        await c.message.edit_text("💎 MITO Basic — доступ к разделам:", reply_markup=_kb_links(BASIC_LINKS))
    else:
        await c.message.edit_text("💎 MITO Pro — полный доступ:", reply_markup=_kb_links(PRO_LINKS))

