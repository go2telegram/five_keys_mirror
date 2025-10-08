from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus, unquote_plus

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.repo import referrals as referrals_repo, subscriptions as subscriptions_repo, users as users_repo
from app.storage import commit_safely

router = Router(name="admin_crud")

_PAGE_SIZE = 20
_ALLOWED_PLANS = {"basic", "pro", "trial", "custom"}
_PERIOD_CHOICES = {"7d", "30d", "all"}


def _is_admin(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    allowed = set(settings.ADMIN_USER_IDS or [])
    allowed.add(settings.ADMIN_ID)
    return user_id in allowed


def _format_dt(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _format_date(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d")


def _encode_query(q: Optional[str]) -> str:
    return quote_plus(q or "")


def _decode_query(encoded: str) -> str:
    return unquote_plus(encoded)


def _normalize_period(value: Optional[str], *, strict: bool = False) -> str:
    normalized = (value or "all").lower()
    if normalized not in _PERIOD_CHOICES:
        if strict:
            raise ValueError("invalid period")
        return "all"
    return normalized


def _build_pagination_markup(callback: str, page: int, total_pages: int, extra: str):
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="Prev", callback_data=f"{callback}:{page - 1}:{extra}")
    if page < total_pages:
        builder.button(text="Next", callback_data=f"{callback}:{page + 1}:{extra}")
    if builder.buttons:
        builder.adjust(len(builder.buttons))
    back_markup = kb_back_home("home:main")
    for row in back_markup.inline_keyboard:
        builder.row(*row)
    return builder.as_markup()


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


@router.message(Command("admin_help"))
async def admin_help(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    text = (
        "Admin commands:\n"
        "/users [page] [query] - list users\n"
        "/user <id> - show user card\n"
        "/sub_get <id> - show subscription\n"
        "/sub_set <id> <plan> <days> - set or extend subscription\n"
        "/sub_del <id> - delete subscription\n"
        "/refs <id> [period] - list referrals (7d|30d|all)\n"
        "/ref_convert <invited_id> [bonus_days] - mark referral conversion"
    )
    await message.answer(text, reply_markup=kb_back_home("home:main"))


@router.message(Command("users"))
async def list_users(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split(maxsplit=2)
    page = _safe_int(parts[1]) if len(parts) > 1 else 1
    if page is None or page < 1:
        page = 1
    query = parts[2] if len(parts) > 2 else ""
    text, markup = await _render_users(page, query)
    await message.answer(text, reply_markup=markup)


async def _render_users(page: int, query: str):
    if page < 1:
        page = 1
    offset = (page - 1) * _PAGE_SIZE
    async with compat_session(session_scope) as session:
        total = await users_repo.count(session, query or None)
        users = await users_repo.find(session, query or None, _PAGE_SIZE, offset)
    total_pages = max(math.ceil(total / _PAGE_SIZE), 1)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * _PAGE_SIZE
        async with compat_session(session_scope) as session:
            users = await users_repo.find(session, query or None, _PAGE_SIZE, offset)
    lines = [f"Users page {page}/{total_pages} (total {total})"]
    if query:
        lines.append(f"Filter: {query}")
    if not users:
        lines.append("No users found.")
    else:
        for item in users:
            username = f"@{item.username}" if item.username else "-"
            lines.append(f"{item.id} | {username} | {_format_dt(item.created)}")
    text = "\n".join(lines)
    encoded_query = _encode_query(query)
    markup = _build_pagination_markup("crud:users:page", page, total_pages, encoded_query)
    return text, markup


@router.callback_query(F.data.startswith("crud:"))
async def handle_callbacks(query: CallbackQuery) -> None:
    if not _is_admin(query.from_user.id if query.from_user else None):
        await query.answer()
        return
    if not query.data:
        await query.answer("Empty callback")
        return
    try:
        parts = query.data.split(":", 3)
        if len(parts) < 3 or parts[0] != "crud":
            await query.answer("Bad arguments", show_alert=True)
            return
        action = parts[1]
        if action == "users" and parts[2] == "page":
            if len(parts) < 4:
                await query.answer("Bad arguments", show_alert=True)
                return
            rest = parts[3]
            page_str, encoded_query = rest.split(":", 1)
            page = _safe_int(page_str) or 1
            query_text = _decode_query(encoded_query)
            await query.answer()
            text, markup = await _render_users(page, query_text)
            if query.message:
                await query.message.edit_text(text, reply_markup=markup)
        elif action == "refs" and parts[2] == "page":
            if len(parts) < 4:
                await query.answer("Bad arguments", show_alert=True)
                return
            rest = parts[3]
            page_str, extra = rest.split(":", 1)
            ref_id_str, period = extra.split(":", 1)
            page = _safe_int(page_str) or 1
            ref_id = _safe_int(ref_id_str)
            period_text = _normalize_period(_decode_query(period))
            if ref_id is None:
                await query.answer("Bad arguments", show_alert=True)
                return
            await query.answer()
            text, markup = await _render_referrals(ref_id, page, period_text)
            if query.message:
                await query.message.edit_text(text, reply_markup=markup)
        else:
            await query.answer("Bad arguments", show_alert=True)
    except Exception as exc:  # pragma: no cover
        await query.answer(f"Error: {exc}", show_alert=True)


@router.message(Command("user"))
async def user_card(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /user <id>")
        return
    user_id = _safe_int(parts[1])
    if user_id is None:
        await message.answer("Bad arguments")
        return
    async with compat_session(session_scope) as session:
        user = await users_repo.get_by_id(session, user_id)
        if user is None:
            await message.answer("User not found", reply_markup=kb_back_home("home:main"))
            return
        subscription = await subscriptions_repo.get(session, user_id)
        referrals_count = await referrals_repo.count_for(session, user_id)
    username = f"@{user.username}" if user.username else "-"
    referred = str(user.referred_by) if user.referred_by else "-"
    if subscription:
        sub_text = f"Plan {subscription.plan} until {_format_dt(subscription.until)}"
    else:
        sub_text = "No active subscription"
    text = (
        f"User {user.id}\n"
        f"Username: {username}\n"
        f"Created: {_format_dt(user.created)}\n"
        f"Referred by: {referred}\n"
        f"{sub_text}\n"
        f"Referrals: {referrals_count}"
    )
    await message.answer(text, reply_markup=kb_back_home("home:main"))


@router.message(Command("sub_get"))
async def sub_get(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /sub_get <id>")
        return
    user_id = _safe_int(parts[1])
    if user_id is None:
        await message.answer("Bad arguments")
        return
    async with compat_session(session_scope) as session:
        subscription = await subscriptions_repo.get(session, user_id)
    if subscription is None:
        text = "No active subscription"
    else:
        text = (
            f"Plan {subscription.plan}\n"
            f"Since {_format_dt(subscription.since)}\n"
            f"Until {_format_dt(subscription.until)}"
        )
    await message.answer(text, reply_markup=kb_back_home("home:main"))


@router.message(Command("sub_set"))
async def sub_set(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Usage: /sub_set <id> <plan> <days>")
        return
    user_id = _safe_int(parts[1])
    plan = parts[2].lower()
    days = _safe_int(parts[3])
    if user_id is None or days is None or days <= 0 or plan not in _ALLOWED_PLANS:
        await message.answer("Bad arguments")
        return
    try:
        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, user_id)
            subscription = await subscriptions_repo.set_plan(session, user_id, plan, days=days)
            await commit_safely(session)
        text = f"Plan {subscription.plan} until {_format_date(subscription.until)}"
        await message.answer(text, reply_markup=kb_back_home("home:main"))
    except Exception as exc:  # pragma: no cover
        await message.answer(f"Error: {exc}")


@router.message(Command("sub_del"))
async def sub_del(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /sub_del <id>")
        return
    user_id = _safe_int(parts[1])
    if user_id is None:
        await message.answer("Bad arguments")
        return
    async with compat_session(session_scope) as session:
        await subscriptions_repo.delete(session, user_id)
        await commit_safely(session)
    await message.answer("Subscription removed", reply_markup=kb_back_home("home:main"))


@router.message(Command("refs"))
async def refs_list(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Usage: /refs <id> [period]")
        return
    user_id = _safe_int(parts[1])
    if user_id is None:
        await message.answer("Bad arguments")
        return
    try:
        period = _normalize_period(parts[2] if len(parts) > 2 else None, strict=True)
    except ValueError:
        await message.answer("Bad arguments")
        return
    text, markup = await _render_referrals(user_id, 1, period)
    await message.answer(text, reply_markup=markup)


async def _render_referrals(user_id: int, page: int, period: str):
    period = _normalize_period(period)
    if page < 1:
        page = 1
    offset = (page - 1) * _PAGE_SIZE
    async with compat_session(session_scope) as session:
        total = await referrals_repo.count_for(session, user_id, period)
        items = await referrals_repo.list_for(session, user_id, _PAGE_SIZE, offset, period)
    total_pages = max(math.ceil(total / _PAGE_SIZE), 1)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * _PAGE_SIZE
        async with compat_session(session_scope) as session:
            items = await referrals_repo.list_for(session, user_id, _PAGE_SIZE, offset, period)
    lines = [f"Referrals page {page}/{total_pages} (total {total})"]
    lines.append(f"Period: {period}")
    if not items:
        lines.append("No referrals")
    else:
        for ref in items:
            converted = _format_dt(ref.converted_at) if ref.converted_at else "-"
            line = (
                f"{ref.invited_id} | {_format_dt(ref.joined_at)} | " f"converted: {converted} | bonus: {ref.bonus_days}"
            )
            lines.append(line)
    text = "\n".join(lines)
    encoded_period = _encode_query(period)
    markup = _build_pagination_markup("crud:refs:page", page, total_pages, f"{user_id}:{encoded_period}")
    return text, markup


@router.message(Command("ref_convert"))
async def ref_convert(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /ref_convert <invited_id> [bonus_days]")
        return
    invited_id = _safe_int(parts[1])
    bonus_days = _safe_int(parts[2]) if len(parts) > 2 else 0
    if invited_id is None or bonus_days is None or bonus_days < 0:
        await message.answer("Bad arguments")
        return
    async with compat_session(session_scope) as session:
        referral = await referrals_repo.convert(session, invited_id, bonus_days)
        if referral is None:
            await message.answer("User not found", reply_markup=kb_back_home("home:main"))
            return
        if bonus_days > 0:
            current_sub = await subscriptions_repo.get(session, referral.user_id)
            plan = current_sub.plan if current_sub else "trial"
            await users_repo.get_or_create_user(session, referral.user_id)
            await subscriptions_repo.set_plan(session, referral.user_id, plan, days=bonus_days)
        await commit_safely(session)
    await message.answer("Referral updated", reply_markup=kb_back_home("home:main"))
