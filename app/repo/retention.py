from __future__ import annotations

import datetime as dt
from typing import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DailyTip, Event, RetentionJourney, RetentionSetting

_DEFAULT_TZ = settings.TIMEZONE or "UTC"


async def get_or_create_settings(
    session: AsyncSession,
    user_id: int,
    *,
    timezone: str | None = None,
) -> RetentionSetting:
    setting = await session.get(RetentionSetting, user_id)
    if setting is not None:
        if timezone and setting.timezone != timezone:
            setting.timezone = timezone
            await session.flush()
        return setting

    tz = timezone or _DEFAULT_TZ or "UTC"
    setting = RetentionSetting(
        user_id=user_id,
        timezone=tz,
    )
    session.add(setting)
    await session.flush()
    return setting


async def set_tips_enabled(session: AsyncSession, user_id: int, enabled: bool) -> RetentionSetting:
    setting = await get_or_create_settings(session, user_id)
    setting.tips_enabled = enabled
    if not enabled:
        setting.last_tip_sent_at = None
    await session.flush()
    return setting


async def set_tips_time(
    session: AsyncSession, user_id: int, send_time: dt.time
) -> RetentionSetting:
    setting = await get_or_create_settings(session, user_id)
    setting.tips_time = send_time
    await session.flush()
    return setting


async def set_timezone(session: AsyncSession, user_id: int, timezone: str) -> RetentionSetting:
    setting = await get_or_create_settings(session, user_id, timezone=timezone)
    return setting


async def list_tip_candidates(session: AsyncSession) -> Sequence[RetentionSetting]:
    stmt = select(RetentionSetting).where(RetentionSetting.tips_enabled.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars())


async def list_water_candidates(session: AsyncSession) -> Sequence[RetentionSetting]:
    stmt = select(RetentionSetting).where(RetentionSetting.water_enabled.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars())


async def pick_tip(session: AsyncSession, *, exclude_id: int | None = None) -> DailyTip | None:
    stmt = select(DailyTip).order_by(func.random()).limit(1)
    if exclude_id is not None:
        stmt = stmt.where(DailyTip.id != exclude_id)
    result = await session.execute(stmt)
    tip = result.scalar_one_or_none()
    if tip is None and exclude_id is not None:
        fallback = await session.execute(select(DailyTip).limit(1))
        return fallback.scalar_one_or_none()
    return tip


async def update_tip_log(
    session: AsyncSession,
    setting: RetentionSetting,
    *,
    tip: DailyTip,
    sent_at: dt.datetime,
) -> None:
    setting.last_tip_sent_at = sent_at
    setting.last_tip_id = tip.id
    await session.flush()


async def record_water_progress(
    session: AsyncSession,
    setting: RetentionSetting,
    *,
    goal_ml: int,
    reminders: int,
    sent_date: dt.date,
    sent_count: int,
) -> None:
    setting.water_goal_ml = goal_ml
    setting.water_reminders = reminders
    setting.water_last_sent_date = sent_date
    setting.water_sent_count = sent_count
    await session.flush()


async def update_weight(
    session: AsyncSession, setting: RetentionSetting, weight: float | None
) -> None:
    setting.weight_kg = weight
    await session.flush()


async def latest_weight_from_events(session: AsyncSession, user_id: int) -> float | None:
    stmt = select(Event).where(Event.user_id == user_id).order_by(Event.ts.desc()).limit(50)
    result = await session.execute(stmt)
    for event in result.scalars():
        meta = event.meta or {}
        weight = meta.get("weight")
        if weight is None:
            continue
        try:
            return float(weight)
        except (TypeError, ValueError):
            continue
    return None


async def schedule_journey(
    session: AsyncSession,
    user_id: int,
    journey: str,
    when: dt.datetime,
    payload: dict | None = None,
) -> None:
    payload = payload or {}
    if not hasattr(session, "execute"):
        return
    await session.execute(
        delete(RetentionJourney).where(
            RetentionJourney.user_id == user_id,
            RetentionJourney.journey == journey,
            RetentionJourney.sent_at.is_(None),
        )
    )
    session.add(
        RetentionJourney(
            user_id=user_id,
            journey=journey,
            scheduled_at=when,
            payload=payload,
        )
    )
    await session.flush()


async def pending_journeys(
    session: AsyncSession,
    *,
    now: dt.datetime,
    limit: int = 100,
) -> Sequence[RetentionJourney]:
    stmt = (
        select(RetentionJourney)
        .where(
            RetentionJourney.sent_at.is_(None),
            RetentionJourney.scheduled_at <= now,
        )
        .order_by(RetentionJourney.scheduled_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def mark_journeys_sent(
    session: AsyncSession, entries: Iterable[RetentionJourney], *, sent_at: dt.datetime
) -> None:
    for entry in entries:
        entry.sent_at = sent_at
    await session.flush()


async def count_tip_enabled(session: AsyncSession) -> int:
    stmt = select(func.count(RetentionSetting.user_id)).where(
        RetentionSetting.tips_enabled.is_(True)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def count_tip_click_users(session: AsyncSession, since: dt.datetime | None = None) -> int:
    stmt = select(func.count(func.distinct(Event.user_id))).where(Event.name == "daily_tip_click")
    if since is not None:
        stmt = stmt.where(Event.ts >= since)
    result = await session.execute(stmt)
    value = result.scalar_one()
    return int(value or 0)
