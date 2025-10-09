from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PreCheckoutQuery

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import (
    events as events_repo,
    orders as orders_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)
from app.services.payments import (
    TelegramPremiumGateway,
    finalize_successful_payment,
    premium_plans,
    verify_signature,
)
from app.storage import commit_safely
from app.utils import safe_edit_text

router = Router(name="premium")
log = logging.getLogger("premium")


BASIC_LINKS: list[tuple[str, str]] = [
    ("МИТОlife (новости)", "https://t.me/c/1858905974/3331"),
    ("EXTRA (полипренолы)", "https://t.me/c/1858905974/5"),
    ("VITEN (иммунитет)", "https://t.me/c/1858905974/13"),
    ("TÉO GREEN (клетчатка)", "https://t.me/c/1858905974/1205"),
    ("MOBIO (метабиотик)", "https://t.me/c/1858905974/11"),
]

PRO_LINKS: list[tuple[str, str]] = BASIC_LINKS + [
    ("Экспертные эфиры", "https://t.me/c/1858905974/459"),
    ("MITOпрограмма", "https://t.me/c/1858905974/221"),
    ("Маркетинг", "https://t.me/c/1858905974/18"),
    ("ERA Mitomatrix", "https://t.me/c/1858905974/3745"),
]


def _kb_links(pairs: Iterable[tuple[str, str]]) -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

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


def _premium_cta_markup(back_cb: str = "home:main") -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Купить Premium", callback_data="sub:menu")
    kb.button(text="💳 Оплатить в Telegram", callback_data="premium:buy")
    kb.button(text="📋 Что входит", callback_data="premium:info")
    kb.button(text="🏠 Домой", callback_data=back_cb)
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


async def _ensure_user(session, message: Message | CallbackQuery) -> None:
    user = message.from_user if isinstance(message, Message) else message.from_user
    if user is None:
        return
    await users_repo.get_or_create_user(session, user.id, user.username)


def _format_until(renewed_at: datetime | None) -> str:
    if renewed_at is None:
        return "—"
    return renewed_at.strftime("%d.%m.%Y")


async def _send_purchase_link(message: Message, plan: str) -> None:
    fallback = settings.PREMIUM_FALLBACK_URL or settings.TRIBUTE_LINK_PRO or settings.TRIBUTE_LINK_BASIC
    text = (
        "Пока Telegram Payments недоступны. \n"
        "Перейдите по ссылке, чтобы завершить оплату Premium."
    )
    if fallback:
        await message.answer(text, reply_markup=_link_markup(fallback))
    else:
        await message.answer(text)


def _link_markup(url: str) -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=url)
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1)
    return kb.as_markup()


def _premium_benefits() -> str:
    lines = [
        "💎 <b>MITO Premium</b>",
        "", "Что входит:",
        "• Полные персональные рекомендации",
        "• Еженедельный AI-план и обновления",
        "• Закрытые материалы и эфиры",
        "• Поддержка экспертов и сообщества",
        "", "Тарифы:",
    ]
    plans = premium_plans()
    for plan in plans.values():
        price_rub = plan.amount / 100
        lines.append(f"• {plan.title}: {price_rub:.0f} ₽ / {plan.duration_days} дней")
    lines.append("")
    lines.append("Оформите подписку, чтобы получить полный доступ.")
    return "\n".join(lines)


@router.message(Command("premium"))
@router.message(Command("premium_info"))
async def premium_info(message: Message) -> None:
    await message.answer(_premium_benefits(), reply_markup=_premium_cta_markup())


@router.message(Command("buy_premium"))
async def buy_premium(message: Message, command: CommandObject | None = None) -> None:
    plan = (command.args or "basic").strip().lower() if command and command.args else "basic"
    gateway = TelegramPremiumGateway(message.bot)
    if not settings.TELEGRAM_PROVIDER_TOKEN:
        await _send_purchase_link(message, plan)
        return
    try:
        sent = await gateway.send_invoice(message, plan)
    except TelegramBadRequest as exc:
        log.warning("send_invoice failed: %s", exc)
        sent = False
    if not sent:
        await _send_purchase_link(message, plan)


@router.callback_query(F.data == "premium:buy")
async def buy_callback(c: CallbackQuery) -> None:
    if c.message is None:
        await c.answer()
        return
    gateway = TelegramPremiumGateway(c.message.bot)
    if settings.TELEGRAM_PROVIDER_TOKEN:
        sent = await gateway.send_invoice(c.message, "basic")
        if not sent:
            await _send_purchase_link(c.message, "basic")
    else:
        await _send_purchase_link(c.message, "basic")
    await c.answer()


@router.callback_query(F.data == "premium:info")
async def premium_info_callback(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        await safe_edit_text(c.message, _premium_benefits(), _premium_cta_markup())


@router.callback_query(F.data == "premium:menu")
async def premium_menu(c: CallbackQuery) -> None:
    async with compat_session(session_scope) as session:
        await _ensure_user(session, c)
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
            _premium_cta_markup("sub:menu"),
        )
        return

    if plan == "basic":
        await safe_edit_text(c.message, "💎 MITO Basic — доступ к разделам:", _kb_links(BASIC_LINKS))
    else:
        await safe_edit_text(c.message, "💎 MITO Pro — полный доступ:", _kb_links(PRO_LINKS))


@router.message(Command("premium_status"))
async def premium_status(message: Message) -> None:
    async with compat_session(session_scope) as session:
        await _ensure_user(session, message)
        active, sub = await subscriptions_repo.is_active(session, message.from_user.id)
    if not sub:
        await message.answer("Подписка не найдена. Используйте /buy_premium чтобы оформить доступ.")
        return
    status = "активна" if active else sub.status
    until = _format_until(sub.renewed_at)
    await message.answer(
        "\n".join(
            [
                "💎 <b>Статус Premium</b>",
                f"План: <b>{sub.plan.upper()}</b>",
                f"Статус: <b>{status}</b>",
                f"Доступ до: <b>{until}</b>",
            ]
        )
    )


@router.message(Command("premium_cancel"))
async def premium_cancel(message: Message) -> None:
    text = (
        "Чтобы отменить автопродление Telegram, откройте \n"
        "Настройки → Платежи и подписки → Выберите MITO Premium. \n"
        "Если оплачивали на сайте — напишите на support@mito.me."
    )
    await message.answer(text)


@router.message(Command("premium_help"))
async def premium_help(message: Message) -> None:
    text = (
        "FAQ по оплате:\n"
        "• Telegram списывает оплату в последний день периода.\n"
        "• Если платёж не прошёл — повторите /buy_premium.\n"
        "• Вопросы и возвраты: support@mito.me"
    )
    await message.answer(text)


@router.message(Command("premium_gift"))
async def premium_gift(message: Message, command: CommandObject | None = None) -> None:
    admins: set[int] = set()
    if settings.ADMIN_ID:
        admins.add(int(settings.ADMIN_ID))
    admins.update(int(item) for item in settings.ADMIN_USER_IDS or [])
    if message.from_user.id not in admins:
        await message.answer("Команда доступна только администраторам.")
        return
    if not command or not command.args:
        await message.answer("Использование: /premium_gift <user_id> <days>")
        return
    parts = command.args.split()
    if len(parts) != 2:
        await message.answer("Использование: /premium_gift <user_id> <days>")
        return
    try:
        target = int(parts[0])
        days = int(parts[1])
    except ValueError:
        await message.answer("user_id и days должны быть числами")
        return

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, target, None)
        sub = await subscriptions_repo.set_plan(
            session,
            user_id=target,
            plan="basic",
            days=days,
            provider="gift",
            status=subscriptions_repo.STATUS_ACTIVE,
        )
        await commit_safely(session)
    await message.answer(
        f"Выдан доступ пользователю {target} до {_format_until(sub.renewed_at)}"
    )


@router.pre_checkout_query()
async def premium_pre_checkout(query: PreCheckoutQuery) -> None:
    try:
        payload = json.loads(query.invoice_payload)
        signature = verify_signature(payload)
    except Exception:
        await query.answer(ok=False, error_message="Не удалось подтвердить заказ")
        return

    async with compat_session(session_scope) as session:
        order = await orders_repo.get_by_payload_hash(session, signature)
        if order is None:
            await query.answer(ok=False, error_message="Заказ не найден")
            return
        await orders_repo.update_status(session, order, "precheckout")
        await commit_safely(session)
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def premium_success(message: Message) -> None:
    payment = message.successful_payment
    try:
        payload = json.loads(payment.invoice_payload)
        plan = await finalize_successful_payment(
            payload,
            provider_charge_id=payment.provider_payment_charge_id,
        )
    except ValueError as exc:
        log.warning("failed to finalize payment: %s", exc)
        await message.answer("Платёж получен, но не удалось обновить подписку. Мы уже разбираемся.")
        return

    async with compat_session(session_scope) as session:
        sub = await subscriptions_repo.get(session, message.from_user.id)
    until = _format_until(sub.renewed_at if sub else None)
    await message.answer(
        "\n".join(
            [
                "💎 Premium активирован!",
                f"План: {plan.title}",
                f"Доступ до: {until}",
                "Команда /ai_plan теперь открывает персональные планы.",
            ]
        )
    )

    async with compat_session(session_scope) as session:
        await events_repo.log(
            session,
            message.from_user.id,
            "premium_paid",
            {"plan": plan.code, "amount": plan.amount, "currency": plan.currency},
        )
        await commit_safely(session)

