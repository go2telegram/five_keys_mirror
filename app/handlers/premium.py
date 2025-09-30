from aiogram import F, Router
from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import session_scope
from app.repo import subscriptions as subscriptions_repo
from app.repo import users as users_repo

router = Router()

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
    layout = [2] * (len(pairs) // 2) + ([1] if len(pairs) % 2 else []) + [1]
    kb.adjust(*layout)
    return kb.as_markup()


@router.callback_query(F.data == "premium:menu")
async def premium_menu(c: CallbackQuery):
    async with session_scope() as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)

    if not is_active or sub is None:
        await c.message.edit_text("🔒 Premium недоступен. Оформите подписку в разделе «Подписка».")
        return

    if sub.plan == "basic":
        await c.message.edit_text(
            "💎 MITO Basic — доступ к разделам:", reply_markup=_kb_links(BASIC_LINKS)
        )
    else:
        await c.message.edit_text(
            "💎 MITO Pro — полный доступ:", reply_markup=_kb_links(PRO_LINKS)
        )
