"""Start command handlers."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.experiments.ab import select_copy
from app.i18n import gettext, resolve_locale
from app.keyboards import (
    kb_back_home,
    kb_goal_menu,
    kb_main,
    kb_onboarding_entry,
    kb_premium_info_actions,
    kb_quiz_menu,
    kb_recommendation_prompt,
    kb_yes_no,
)
from app.repo import (
    events as events_repo,
    profiles as profiles_repo,
    referrals as referrals_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)
from app.config import settings
from app import build_info
from app.feature_flags import feature_flags
from app.storage import commit_safely, grant_role, has_role, touch_throttle
from app.texts import Texts
from app.utils import safe_edit_text
from app.link_manager import get_register_link

from app.quiz.engine import start_quiz

from app.growth import attribution as growth_attribution

from app.handlers import reg as reg_handlers

logger = logging.getLogger(__name__)
log_start = logging.getLogger("start")

router = Router(name="start")

START_THROTTLE_SECONDS = 3.0
ADMIN_PANEL_THROTTLE = 5.0
ADMIN_ROLE = "admin"


def _texts_for_user(language_code: str | None) -> Texts:
    locale = resolve_locale(language_code)
    return Texts(locale)


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


def greeting_for_user(user_id: int | None, texts: Texts) -> str:
    if feature_flags.is_enabled("FF_NEW_ONBOARDING", user_id=user_id):
        return texts.nav.greeting_fresh()
    return texts.nav.greeting_classic()


def _confirmation_for_user(user_id: int | None, texts: Texts) -> str:
    if feature_flags.is_enabled("FF_NEW_ONBOARDING", user_id=user_id):
        return texts.nav.onboarding_confirmation_fresh()
    return texts.nav.onboarding_confirmation_classic()


def _returning_prompt(user_id: int | None, texts: Texts) -> str:
    if feature_flags.is_enabled("FF_NEW_ONBOARDING", user_id=user_id):
        return texts.nav.returning_prompt_fresh()
    return texts.nav.returning_prompt_classic()


@router.message(CommandStart())
async def start_safe(message: Message) -> None:
    """Send the greeting immediately and schedule the heavy logic."""

    text = message.text or ""
    payload = text.split(" ", 1)[1] if " " in text else ""

    user_id = getattr(message.from_user, "id", None)
    if _is_admin(user_id):
        log_start.debug("START admin detected uid=%s", user_id)

    texts = _texts_for_user(getattr(message.from_user, "language_code", None))

    remaining = touch_throttle(user_id, "start:command", START_THROTTLE_SECONDS)
    if remaining > 0:
        log_start.info("START throttled uid=%s remaining=%.2f", user_id, remaining)
        await message.answer(texts.common.throttle_in_progress())
        return

    log_start.info(
        "START uid=%s uname=%s",
        getattr(message.from_user, "id", None),
        getattr(message.from_user, "username", None),
    )

    greeting = greeting_for_user(user_id, texts)
    await message.answer(greeting, reply_markup=kb_onboarding_entry(user_id=user_id))

    asyncio.create_task(_start_full(message, payload, texts.locale))


@router.message(Command("menu"))
async def command_menu(message: Message) -> None:
    texts = _texts_for_user(getattr(message.from_user, "language_code", None))
    await message.answer(texts.common.welcome(), reply_markup=kb_main())


async def _start_full(message: Message, payload: str, locale: str) -> None:
    """Execute the database-heavy part of the /start flow in the background."""

    try:
        tg_id = message.from_user.id
        username = message.from_user.username
        existing_user = None
        already_prompted = None

        async with compat_session(session_scope) as session:
            existing_user = await users_repo.get_user(session, tg_id)
            await users_repo.get_or_create_user(session, tg_id, username)
            await events_repo.log(session, tg_id, "start", {"payload": payload})

            utm_data = growth_attribution.parse_utm_payload(payload)
            if utm_data:
                await profiles_repo.save_utm(session, tg_id, utm_data)

            if payload.startswith("ref_"):
                try:
                    ref_id = int(payload.split("_", 1)[1])
                except (ValueError, IndexError):
                    ref_id = None
                if ref_id and ref_id != tg_id:
                    await users_repo.get_or_create_user(session, ref_id)
                    await referrals_repo.upsert_referral(session, ref_id, tg_id)
                    await users_repo.set_referrer(session, tg_id, ref_id)
                    await events_repo.upsert(session, tg_id, "ref_join", {"referrer_id": ref_id})

            already_prompted = await events_repo.last_by(session, tg_id, "notify_prompted")
            await commit_safely(session)

        is_new_user = existing_user is None

        async with compat_session(session_scope) as session:
            is_premium, _ = await subscriptions_repo.is_active(session, tg_id)
            await commit_safely(session)
        texts = Texts(locale)

        if is_premium:
            await message.answer(texts.common.premium_welcome())

        if not already_prompted:
            async with compat_session(session_scope) as session:
                await events_repo.upsert(session, tg_id, "notify_prompted", {})
                await commit_safely(session)
            await message.answer(
                texts.common.ask_notify(),
                reply_markup=kb_yes_no("notify:yes", "notify:no"),
            )

        if is_new_user:
            await _start_registration(message, texts)
        else:
            await _prompt_recommendations(message, texts)
    except Exception:  # noqa: BLE001 - log unexpected issues without breaking /start
        logger.exception("start_full failed")


async def _start_registration(message: Message, texts: Texts) -> None:
    url = await get_register_link()
    if url:
        await message.answer(
            texts.common.registration_prompt(),
            reply_markup=reg_handlers.build_reg_markup(url, texts),
        )
    else:
        await message.answer(texts.common.registration_prompt())


async def _prompt_recommendations(message: Message, texts: Texts) -> None:
    user_id = getattr(message.from_user, "id", None)
    prompt = _returning_prompt(user_id, texts)
    await message.answer(prompt, reply_markup=kb_recommendation_prompt(user_id=user_id))


@router.callback_query(F.data == "onboard:energy")
async def onboarding_energy(c: CallbackQuery, state: FSMContext) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await c.message.answer(_confirmation_for_user(getattr(c.from_user, "id", None), texts))
    await start_quiz(c, state, "energy")


@router.callback_query(F.data == "onboard:recommend")
async def onboarding_recommend(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await c.message.answer(_confirmation_for_user(getattr(c.from_user, "id", None), texts))
        await c.message.answer(texts.nav.recommend_goal_prompt(), reply_markup=kb_goal_menu())


@router.callback_query(F.data == "onboard:recommend_full")
async def onboarding_recommend_full(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await c.message.answer(_confirmation_for_user(getattr(c.from_user, "id", None), texts))
        locale = texts.locale
        user_id = getattr(c.from_user, "id", "anon")
        ab_copy = select_copy(
            None,
            "recommend_full_copy",
            str(user_id),
            context={"locale": locale},
        )
        copy = ab_copy or gettext("recommend.full_prompt", locale)
        await c.message.answer(
            copy,
            reply_markup=kb_recommendation_prompt(user_id=getattr(c.from_user, "id", None)),
        )


@router.callback_query(F.data == "onboard:register")
async def onboarding_register(c: CallbackQuery) -> None:
    return await reg_handlers.reg_open(c)


@router.callback_query(F.data == "menu:tests")
async def menu_tests(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await safe_edit_text(
            c.message,
            texts.nav.menu_tests(),
            kb_quiz_menu(),
        )


@router.callback_query(F.data == "menu:premium")
async def menu_premium(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await safe_edit_text(
            c.message,
            texts.nav.menu_premium(),
            kb_premium_info_actions(),
        )


@router.callback_query(F.data == "menu:help")
async def menu_help(c: CallbackQuery) -> None:
    await c.answer()
    if c.message:
        texts = _texts_for_user(getattr(c.from_user, "language_code", None))
        await safe_edit_text(c.message, texts.nav.menu_help(), kb_back_home())


@router.callback_query(F.data == "notify:yes")
async def notify_yes(c: CallbackQuery):
    await c.answer()
    texts = _texts_for_user(getattr(c.from_user, "language_code", None))
    async with compat_session(session_scope) as session:
        await events_repo.log(session, c.from_user.id, "notify_on", {})
        await commit_safely(session)
    await safe_edit_text(c.message, texts.common.notify_on())


@router.callback_query(F.data == "notify:no")
async def notify_no(c: CallbackQuery):
    await c.answer()
    texts = _texts_for_user(getattr(c.from_user, "language_code", None))
    async with compat_session(session_scope) as session:
        await events_repo.log(session, c.from_user.id, "notify_off", {})
        await commit_safely(session)
    await safe_edit_text(c.message, texts.common.notify_off())


@router.message(Command("version"))
async def version_command(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    texts = _texts_for_user(getattr(message.from_user, "language_code", None))
    if not _is_admin(user_id):
        await message.answer(texts.common.admin_only())
        return

    branch = getattr(build_info, "GIT_BRANCH", "unknown")
    commit = getattr(build_info, "GIT_COMMIT", "unknown")
    build_time = getattr(build_info, "BUILD_TIME", "unknown")
    await message.answer(texts.common.version_report(branch, commit, build_time))


@router.message(Command("panel"))
async def panel_command(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    texts = _texts_for_user(getattr(message.from_user, "language_code", None))
    if not _is_admin(user_id):
        await message.answer(texts.common.admin_only())
        return

    remaining = touch_throttle(user_id, "admin:panel", ADMIN_PANEL_THROTTLE)
    if remaining > 0:
        await message.answer(texts.common.panel_busy())
        return

    await message.answer(texts.nav.admin_panel_help())
