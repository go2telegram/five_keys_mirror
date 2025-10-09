from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.config import settings
from app.db.session import compat_session, session_scope
from app.repo import daily_tips as daily_tips_repo, events as events_repo, users as users_repo
from app.storage import commit_safely

DEFAULT_TIME = dt.time(hour=10, minute=0)


@dataclass(slots=True)
class DailyTipSchedule:
    timezone: str
    next_fire: dt.datetime | None


def _resolve_timezone(preferred: str | None) -> ZoneInfo:
    tz_name = preferred or settings.TIMEZONE or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:  # pragma: no cover - fallback for invalid tz database
        return ZoneInfo("UTC")


def compute_next_fire(
    *,
    timezone: str | None,
    now: dt.datetime | None = None,
    at: dt.time = DEFAULT_TIME,
) -> dt.datetime:
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    zone = _resolve_timezone(timezone)
    local = moment.astimezone(zone)
    fire_local = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if fire_local <= local:
        fire_local = fire_local + dt.timedelta(days=1)
    return fire_local.astimezone(dt.timezone.utc)


async def schedule_next_tip(
    user_id: int,
    *,
    timezone: str,
    now: dt.datetime | None = None,
) -> DailyTipSchedule:
    next_fire = compute_next_fire(timezone=timezone, now=now)
    async with compat_session(session_scope) as session:
        await daily_tips_repo.set_enabled(
            session,
            user_id,
            enabled=True,
            next_send_at=next_fire,
        )
        await commit_safely(session)
    return DailyTipSchedule(timezone=timezone, next_fire=next_fire)


async def disable_tip_schedule(user_id: int) -> None:
    async with compat_session(session_scope) as session:
        await daily_tips_repo.set_enabled(session, user_id, enabled=False)
        await commit_safely(session)


async def send_daily_tip(bot: Bot, user_id: int, tip_text: str) -> None:
    await bot.send_message(user_id, f"🔹 {tip_text}")


async def dispatch_due_tips(bot: Bot, *, limit: int = 64) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    sent = 0
    async with compat_session(session_scope) as session:
        due = await daily_tips_repo.due_subscriptions(session, now, limit=limit)
        queue = [(item.user_id, item.timezone) for item in due]
    if not queue:
        return 0

    for user_id, timezone in queue:
        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, user_id)
            subscription = await daily_tips_repo.get_or_create_subscription(
                session,
                user_id,
                default_timezone=timezone,
            )
            tip = await daily_tips_repo.random_tip(session)
            if tip is None:
                await commit_safely(session)
                continue
            await events_repo.log(
                session,
                user_id,
                "daily_tip_sent",
                {"tip_id": tip.id},
            )
            next_fire = compute_next_fire(timezone=subscription.timezone, now=now)
            await daily_tips_repo.mark_sent(
                session,
                subscription,
                next_send_at=next_fire,
                tip_id=tip.id,
            )
            await commit_safely(session)
        try:
            await send_daily_tip(bot, user_id, tip.text)
        except Exception:  # pragma: no cover - network errors should not abort loop
            continue
        sent += 1
    return sent


async def immediate_tip(bot: Bot, user_id: int) -> str | None:
    async with compat_session(session_scope) as session:
        tip = await daily_tips_repo.random_tip(session)
        if tip is None:
            return None
        await users_repo.get_or_create_user(session, user_id)
        await events_repo.log(session, user_id, "daily_tip_view", {"tip_id": tip.id})
        await commit_safely(session)
    await send_daily_tip(bot, user_id, tip.text)
    return tip.text
