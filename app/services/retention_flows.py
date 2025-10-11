"""Retention flow helpers used by scheduled jobs."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RetentionPush


@dataclass(slots=True)
class RetentionState:
    """Snapshot of user activity relevant for retention decisions."""

    user_id: int
    last_activity: dt.datetime | None = None
    last_energy_test: dt.datetime | None = None
    has_premium: bool = False
    last_pushes: Dict[str, dt.datetime] = field(default_factory=dict)


@dataclass(slots=True)
class RetentionPushPayload:
    """Information about a retention push message."""

    kind: str
    message: str
    scheduled_at: dt.datetime


class RetentionManager:
    """Decides which retention pushes should be sent."""

    FLOW_ENERGY = "energy_test"
    FLOW_PREMIUM = "premium_offer"

    def __init__(
        self,
        inactivity_threshold: dt.timedelta | None = dt.timedelta(hours=24),
        premium_threshold: dt.timedelta | None = dt.timedelta(hours=72),
    ) -> None:
        self.inactivity_threshold = inactivity_threshold
        self.premium_threshold = premium_threshold

    async def load_state(self, session: AsyncSession, user_id: int) -> RetentionState:
        stmt = select(RetentionPush).where(RetentionPush.user_id == user_id)
        result = await session.execute(stmt)
        pushes = {row.flow: row.last_sent for row in result.scalars()}
        return RetentionState(user_id=user_id, last_pushes=pushes)

    async def remember_push(self, session: AsyncSession, user_id: int, kind: str, when: dt.datetime) -> None:
        stmt = select(RetentionPush).where(RetentionPush.user_id == user_id, RetentionPush.flow == kind)
        result = await session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            session.add(RetentionPush(user_id=user_id, flow=kind, last_sent=when))
        else:
            model.last_sent = when
        await session.flush()

    def evaluate(self, state: RetentionState, now: dt.datetime | None = None) -> list[RetentionPushPayload]:
        now = now or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        pushes: list[RetentionPushPayload] = []

        if (
            self.inactivity_threshold is not None
            and not state.has_premium
            and _should_trigger(state.last_activity, self.inactivity_threshold, now)
            and _should_send_again(state.last_pushes.get(self.FLOW_ENERGY), state.last_activity, now)
        ):
            pushes.append(
                RetentionPushPayload(
                    kind=self.FLOW_ENERGY,
                    message="⚡ Пройти тест энергии",
                    scheduled_at=now,
                )
            )

        if (
            self.premium_threshold is not None
            and not state.has_premium
            and _should_trigger(state.last_energy_test, self.premium_threshold, now)
            and _should_send_again(state.last_pushes.get(self.FLOW_PREMIUM), state.last_energy_test, now)
        ):
            pushes.append(
                RetentionPushPayload(
                    kind=self.FLOW_PREMIUM,
                    message="💎 Попробовать Премиум",
                    scheduled_at=now,
                )
            )

        return pushes


def _should_trigger(last_event: dt.datetime | None, threshold: dt.timedelta, now: dt.datetime) -> bool:
    if last_event is None:
        return True
    if last_event.tzinfo is None:
        last_event = last_event.replace(tzinfo=dt.timezone.utc)
    return now - last_event >= threshold


def _should_send_again(
    last_push: dt.datetime | None,
    reference: dt.datetime | None,
    now: dt.datetime,
) -> bool:
    if last_push is None:
        return True
    if last_push.tzinfo is None:
        last_push = last_push.replace(tzinfo=dt.timezone.utc)
    if reference is not None and reference.tzinfo is None:
        reference = reference.replace(tzinfo=dt.timezone.utc)

    if reference is not None and last_push >= reference:
        return False
    return (now - last_push) >= dt.timedelta(hours=12)
