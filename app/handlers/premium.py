from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import events as events_repo, subscriptions as subscriptions_repo, users as users_repo
from app.storage import commit_safely
from app.utils import safe_edit_text
from app.utils.premium_cta import CTA_BUTTON_TEXT

router = Router(name="premium")

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


FREE_BULLETS = [
    "Базовые рекомендации после квизов и калькуляторов.",
    "Подбор продуктов и PDF без регулярных обновлений.",
    "Доступ к открытым материалам канала.",
]

PREMIUM_BULLETS = [
    "AI-план на неделю под твою цель.",
    "Еженедельные апдейты и напоминания от эксперта.",
    "Закрытые эфиры, чек-листы и разборы кейсов.",
]

PREMIUM_INFO_TEXT = (
    "💎 <b>MITO Premium</b> — расширенный доступ\n\n"
    "<b>Free</b>:\n" + "\n".join(f"• {item}" for item in FREE_BULLETS) + "\n\n"
    "<b>Premium</b>:\n" + "\n".join(f"• {item}" for item in PREMIUM_BULLETS) + "\n\n"
    "Открой Premium, чтобы получить полный план и сопровождение."
)


def _kb_links(pairs):
    kb = InlineKeyboardBuilder()
    for title, url in pairs:
        kb.button(text=f"🔗 {title}", url=url)
    for row in kb_back_home("sub:menu").inline_keyboard:
        kb.row(*row)
    layout = [2] * (len(pairs) // 2)
    if len(pairs) % 2:
        layout.append(1)
    layout.extend([2])
    kb.adjust(*layout)
    return kb.as_markup()


def _kb_premium_info(back_cb: str | None = None):
    kb = InlineKeyboardBuilder()
    kb.button(text="/buy_premium", callback_data="premium:buy")
    kb.adjust(1)
    for row in kb_back_home(back_cb).inline_keyboard if back_cb else kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb.as_markup()


def _kb_premium_buy(back_cb: str | None = None):
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
    if not (settings.TRIBUTE_LINK_BASIC or settings.TRIBUTE_LINK_PRO):
        kb.button(text="Написать консультанту", url="https://t.me/Nat988988")
    kb.adjust(1)
    for row in kb_back_home(back_cb).inline_keyboard if back_cb else kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb.as_markup()


async def _log_event(
    callback: CallbackQuery | Message, event: str, meta: dict | None = None
) -> None:
    user = callback.from_user if isinstance(callback, CallbackQuery) else callback.from_user
    if user is None:
        return
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user.id, getattr(user, "username", None))
        await events_repo.log(session, user.id, event, meta or {})
        await commit_safely(session)


async def _send_info(
    target: CallbackQuery | Message, *, replace: bool = False, back_cb: str | None = None
) -> None:
    markup = _kb_premium_info(back_cb)
    if isinstance(target, CallbackQuery):
        if replace and target.message is not None:
            await safe_edit_text(target.message, PREMIUM_INFO_TEXT, markup)
        elif target.message is not None:
            await target.message.answer(PREMIUM_INFO_TEXT, reply_markup=markup)
    else:
        await target.answer(PREMIUM_INFO_TEXT, reply_markup=markup)


async def _send_buy(
    target: CallbackQuery | Message, *, replace: bool = False, back_cb: str | None = None
) -> None:
    markup = _kb_premium_buy(back_cb)
    text = (
        "Выберите тариф MITO Premium:\n"
        "• Basic — доступ к базовым материалам и апдейтам.\n"
        "• Pro — полный пакет Premium с клубом и эфирами."
    )
    if isinstance(target, CallbackQuery):
        if replace and target.message is not None:
            await safe_edit_text(target.message, text, markup)
        elif target.message is not None:
            await target.message.answer(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(Command("premium_info"))
async def premium_info_command(message: Message) -> None:
    await _log_event(message, "premium_info_open", {"source": "command"})
    await message.answer(PREMIUM_INFO_TEXT, reply_markup=_kb_premium_info())


@router.message(Command("buy_premium"))
async def buy_premium_command(message: Message) -> None:
    await _log_event(message, "premium_buy_open", {"source": "command"})
    await message.answer(
        "Готово! Выберите тариф MITO Premium:",
        reply_markup=_kb_premium_buy(),
    )


@router.callback_query(F.data == "premium:info")
async def premium_info_callback(c: CallbackQuery) -> None:
    await _log_event(c, "premium_info_open", {"source": "menu"})
    await c.answer()
    await _send_info(c, replace=True, back_cb="premium:menu")


@router.callback_query(F.data == "premium:buy")
async def premium_buy_callback(c: CallbackQuery) -> None:
    await _log_event(c, "premium_buy_open", {"source": "menu"})
    await c.answer()
    await _send_buy(c, replace=True, back_cb="premium:menu")


@router.callback_query(F.data.startswith("premium:cta:"))
async def premium_cta_open(c: CallbackQuery) -> None:
    parts = (c.data or "").split(":", 2)
    source = parts[-1] if len(parts) == 3 else "unknown"
    await _log_event(c, "premium_cta_click", {"source": source})
    await _log_event(c, "premium_info_open", {"source": f"cta:{source}"})
    await c.answer(text=CTA_BUTTON_TEXT, show_alert=False)
    await _send_info(c, replace=True, back_cb="premium:menu")


@router.callback_query(F.data == "premium:menu")
async def premium_menu(c: CallbackQuery):
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, c.from_user.id, c.from_user.username)
        is_active, sub = await subscriptions_repo.is_active(session, c.from_user.id)
        plan = sub.plan if sub else None
        await events_repo.log(
            session,
            c.from_user.id,
            "premium_open",
            {"active": is_active, "plan": plan},
        )
        await commit_safely(session)

    await c.answer()
    if not is_active or plan is None:
        await safe_edit_text(
            c.message,
            "🔒 Premium доступен только с активной подпиской.",
            kb_back_home("sub:menu"),
        )
        return

    if plan == "basic":
        await safe_edit_text(
            c.message,
            "💎 MITO Basic — доступ к разделам:",
            _kb_links(BASIC_LINKS),
        )
    else:
        await safe_edit_text(
            c.message,
            "💎 MITO Pro — полный доступ:",
            _kb_links(PRO_LINKS),
        )
