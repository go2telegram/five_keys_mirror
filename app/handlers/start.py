"""Start command handlers."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.keyboards import kb_main, kb_yes_no
from app.repo import events as events_repo, referrals as referrals_repo, users as users_repo
from app.config import settings
from app import build_info
from app.storage import commit_safely, grant_role, has_role, touch_throttle
from app.texts import ASK_NOTIFY, NOTIFY_OFF, NOTIFY_ON

logger = logging.getLogger(__name__)
log_start = logging.getLogger("start")

router = Router(name="start")

GREETING = (
    "\u041f\u0440\u0438\u0432\u0435\u0442! \u041d\u0430 \u0441\u0432\u044f\u0437\u0438 "
    "\xab\u041f\u044f\u0442\u044c \u043a\u043b\u044e\u0447\u0435\u0439 \u0437\u0434\u043e\u0440\u043e\u0432\u044c\u044f"
    "\xbb. "
    "\u0412\u044b\u0431\u0438\u0440\u0430\u0439 \u0440\u0430\u0437\u0434\u0435\u043b "
    "\u0432 \u043c\u0435\u043d\u044e \u043d\u0438\u0436\u0435:"
)

START_THROTTLE_SECONDS = 3.0
ADMIN_PANEL_THROTTLE = 5.0
ADMIN_ROLE = "admin"


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    admin_ids: set[int] = set()
    if settings.ADMIN_ID:
        admin_ids.add(int(settings.ADMIN_ID))
    admin_ids.update(int(item) for item in settings.ADMIN_USER_IDS or [])
    if user_id in admin_ids:
        grant_role(user_id, ADMIN_ROLE)
        return True
    return has_role(user_id, ADMIN_ROLE)


@router.message(CommandStart())
async def start_safe(message: Message) -> None:
    """Send the greeting immediately and schedule the heavy logic."""

    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    user_id = getattr(message.from_user, "id", None)
    if _is_admin(user_id):
        log_start.debug("START admin detected uid=%s", user_id)

    remaining = touch_throttle(user_id, "start:command", START_THROTTLE_SECONDS)
    if remaining > 0:
        log_start.info("START throttled uid=%s remaining=%.2f", user_id, remaining)
        await message.answer("Команда уже выполняется, попробуйте позже.")
        return

    log_start.info(
        "START uid=%s uname=%s",
        getattr(message.from_user, "id", None),
        getattr(message.from_user, "username", None),
    )

    await message.answer(GREETING, reply_markup=kb_main())

    asyncio.create_task(_start_full(message, payload))


async def _start_full(message: Message, payload: str) -> None:
    """Execute the database-heavy part of the /start flow in the background."""

    try:
        tg_id = message.from_user.id
        username = message.from_user.username

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, tg_id, username)
            await events_repo.log(session, tg_id, "start", {"payload": payload})

            if payload.startswith("ref_"):
                try:
                    ref_id = int(payload.split("_", 1)[1])
                except (ValueError, IndexError):
                    ref_id = None
                if ref_id and ref_id != tg_id:
                    await users_repo.get_or_create_user(session, ref_id)
                    existing_ref = await referrals_repo.get_by_invited(session, tg_id)
                    if existing_ref is None:
                        await referrals_repo.create(session, ref_id, tg_id)
                    await users_repo.set_referrer(session, tg_id, ref_id)
                    await events_repo.log(session, tg_id, "ref_join", {"referrer_id": ref_id})

            already_prompted = await events_repo.last_by(session, tg_id, "notify_prompted")
            await commit_safely(session)

        if not already_prompted:
            async with compat_session(session_scope) as session:
                await events_repo.log(session, tg_id, "notify_prompted", {})
                await commit_safely(session)
            await message.answer(
                ASK_NOTIFY,
                reply_markup=kb_yes_no("notify:yes", "notify:no"),
            )
    except Exception:  # noqa: BLE001 - log unexpected issues without breaking /start
        logger.exception("start_full failed")


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    await c.answer()
    async with compat_session(session_scope) as session:
        await events_repo.log(session, c.from_user.id, "notify_on", {})
        await commit_safely(session)
    await c.message.edit_text(NOTIFY_ON)


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    await c.answer()
    async with compat_session(session_scope) as session:
        await events_repo.log(session, c.from_user.id, "notify_off", {})
        await commit_safely(session)
    await c.message.edit_text(NOTIFY_OFF)


@router.message(Command("version"))
async def version_command(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    if not _is_admin(user_id):
        await message.answer("Команда доступна только администраторам.")
        return

    lines = [
        "🤖 Текущая версия бота:",
        f"branch: {getattr(build_info, 'GIT_BRANCH', 'unknown')}",
        f"commit: {getattr(build_info, 'GIT_COMMIT', 'unknown')}",
        f"build_time: {getattr(build_info, 'BUILD_TIME', 'unknown')}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("panel"))
async def panel_command(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    if not _is_admin(user_id):
        await message.answer("Команда доступна только администраторам.")
        return

    remaining = touch_throttle(user_id, "admin:panel", ADMIN_PANEL_THROTTLE)
    if remaining > 0:
        await message.answer("Панель уже открыта, попробуйте позже.")
        return

    lines = [
        "🛠 Админ-панель",
        "Используй команды:",
        "• /stats — ключевые метрики",
        "• /leads — последние лиды",
        "• /leads_csv 500 — выгрузка лидов",
        "• /reg — открыть регистрацию",
    ]
    await message.answer("\n".join(lines))
