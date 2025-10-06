from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.models import AdminEvent, Lead, Subscription, User, Product
from app.db.session import session_scope

# временные состояния/ивенты остаются ин-мемори
SESSIONS: Dict[int, Dict[str, Any]] = {}
EVENTS: list[Dict[str, Any]] = []


@dataclass(slots=True)
class SubscriptionInfo:
    plan: str
    since: dt.datetime
    until: Optional[dt.datetime]
    product_code: Optional[str] = None


@dataclass(slots=True)
class UserProfile:
    telegram_id: int
    timezone: str
    source: Optional[str]
    asked_notify: bool
    notify_enabled: bool
    ref_code: str
    referred_by: Optional[int]
    ref_clicks: int
    ref_joins: int
    ref_conversions: int
    ref_users: set[int]
    last_plan: dict
    subscription: Optional[SubscriptionInfo]
    extra: dict


@dataclass(slots=True)
class LeadRecord:
    id: int
    user_id: Optional[int]
    username: Optional[str]
    name: str
    phone: str
    comment: Optional[str]
    created_at: dt.datetime
    metadata: dict


@dataclass(slots=True)
class AdminEventRecord:
    id: int
    kind: str
    payload: dict
    created_at: dt.datetime


def _map_subscription(orm_sub: Subscription | None) -> SubscriptionInfo | None:
    if orm_sub is None:
        return None
    return SubscriptionInfo(
        plan=orm_sub.plan_code or "",
        since=orm_sub.started_at,
        until=orm_sub.expires_at,
        product_code=orm_sub.product.code if orm_sub.product else None,
    )


def _map_user(orm_user: User, subscription: Subscription | None = None) -> UserProfile:
    sub = _map_subscription(subscription)
    return UserProfile(
        telegram_id=orm_user.telegram_id,
        timezone=orm_user.timezone,
        source=orm_user.source,
        asked_notify=orm_user.asked_notify,
        notify_enabled=orm_user.notify_enabled,
        ref_code=orm_user.ref_code,
        referred_by=(orm_user.referred_by.telegram_id if orm_user.referred_by else None),
        ref_clicks=orm_user.ref_clicks,
        ref_joins=orm_user.ref_joins,
        ref_conversions=orm_user.ref_conversions,
        ref_users=set(orm_user.ref_users or []),
        last_plan=dict(orm_user.last_plan or {}),
        subscription=sub,
        extra=dict(orm_user.extra or {}),
    )


def _map_lead(lead: Lead) -> LeadRecord:
    return LeadRecord(
        id=lead.id,
        user_id=lead.user.telegram_id if lead.user else None,
        username=lead.username,
        name=lead.name,
        phone=lead.phone,
        comment=lead.comment,
        created_at=lead.created_at,
        metadata=dict(lead.meta or {}),
    )


def _map_admin_event(event: AdminEvent) -> AdminEventRecord:
    return AdminEventRecord(
        id=event.id,
        kind=event.kind,
        payload=dict(event.payload or {}),
        created_at=event.created_at,
    )


async def _load_user(session, tg_id: int) -> User | None:
    stmt = select(User).where(User.telegram_id == tg_id).options(selectinload(User.referred_by))
    return await session.scalar(stmt)


async def _load_active_subscription(session, user_id: int) -> Subscription | None:
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status == "active")
        .options(selectinload(Subscription.product))
    )
    return await session.scalar(stmt)


async def ensure_user(tg_id: int, *, source: Optional[str] = None) -> tuple[UserProfile, bool]:
    async with session_scope() as session:
        user = await _load_user(session, tg_id)
        created = False
        if user is None:
            user = User(telegram_id=tg_id, ref_code=str(tg_id))
            session.add(user)
            await session.flush()
            created = True
        if user.source is None and source:
            user.source = source
        sub = await _load_active_subscription(session, user.id)
        return _map_user(user, sub), created


async def log_admin_event(kind: str, payload: Optional[dict] = None) -> AdminEventRecord:
    async with session_scope() as session:
        event = AdminEvent(kind=kind, payload=payload or {})
        session.add(event)
        await session.flush()
        await session.refresh(event)
        return _map_admin_event(event)


async def fetch_admin_events(
    kind: Optional[str] = None,
    *,
    since: Optional[dt.datetime] = None,
    limit: Optional[int] = None,
) -> list[AdminEventRecord]:
    async with session_scope() as session:
        stmt = select(AdminEvent)
        if kind:
            stmt = stmt.where(AdminEvent.kind == kind)
        if since:
            stmt = stmt.where(AdminEvent.created_at >= since)
        stmt = stmt.order_by(AdminEvent.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)
        records = await session.scalars(stmt)
        return [_map_admin_event(item) for item in records]


async def count_admin_events(
    kind: Optional[str] = None,
    *,
    since: Optional[dt.datetime] = None,
) -> int:
    async with session_scope() as session:
        stmt = select(func.count()).select_from(AdminEvent)
        if kind:
            stmt = stmt.where(AdminEvent.kind == kind)
        if since:
            stmt = stmt.where(AdminEvent.created_at >= since)
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def get_user(tg_id: int) -> Optional[UserProfile]:
    async with session_scope() as session:
        user = await _load_user(session, tg_id)
        if user is None:
            return None
        sub = await _load_active_subscription(session, user.id)
        return _map_user(user, sub)


async def mutate_user(
    tg_id: int,
    mutator: Callable[[User, Any], None],
    *,
    ensure: bool = True,
) -> UserProfile:
    async with session_scope() as session:
        user = await _load_user(session, tg_id)
        if user is None:
            if not ensure:
                raise KeyError(f"user {tg_id} not found")
            user = User(telegram_id=tg_id, ref_code=str(tg_id))
            session.add(user)
            await session.flush()
        maybe_coro = mutator(user, session)
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro
        sub = await _load_active_subscription(session, user.id)
        return _map_user(user, sub)


async def set_notify(tg_id: int, enabled: bool) -> UserProfile:
    return await mutate_user(tg_id, lambda u, _: setattr(u, "notify_enabled", enabled))


async def set_asked_notify(tg_id: int) -> UserProfile:
    return await mutate_user(tg_id, lambda u, _: setattr(u, "asked_notify", True))


async def update_timezone(tg_id: int, tz: str) -> UserProfile:
    return await mutate_user(tg_id, lambda u, _: setattr(u, "timezone", tz))


async def set_source(tg_id: int, source: Optional[str]) -> UserProfile:
    return await mutate_user(tg_id, lambda u, _: setattr(u, "source", source))


async def add_ref_click(referrer_tg_id: int, user_tg_id: int, *, new_join: bool) -> UserProfile:
    def _mutator(user: User, _session: Any) -> None:
        if user.ref_users is None:
            user.ref_users = []
        is_new = False
        if user_tg_id not in user.ref_users:
            user.ref_users.append(user_tg_id)
            is_new = True
        if is_new:
            user.ref_clicks += 1
        if new_join:
            user.ref_joins += 1

    return await mutate_user(referrer_tg_id, _mutator)


async def set_referred_by(tg_id: int, referrer_tg_id: Optional[int]) -> UserProfile:
    async def _mutator(user: User, session: Any) -> None:
        if referrer_tg_id is None:
            user.referred_by = None
            return
        referrer = await _load_user(session, referrer_tg_id)
        if referrer is None:
            referrer = User(telegram_id=referrer_tg_id, ref_code=str(referrer_tg_id))
            session.add(referrer)
            await session.flush()
        user.referred_by = referrer

    return await mutate_user(tg_id, _mutator)


async def increment_ref_conversion(referrer_tg_id: int) -> UserProfile:
    return await mutate_user(referrer_tg_id, lambda u, _: setattr(u, "ref_conversions", u.ref_conversions + 1))


async def set_last_plan(user_id: int, plan: dict) -> None:
    await mutate_user(user_id, lambda u, _: setattr(u, "last_plan", plan))


async def get_last_plan(user_id: int) -> dict | None:
    profile = await get_user(user_id)
    return profile.last_plan if profile else None


async def save_event(user_id: Optional[int], source: Optional[str], action: str, payload: Optional[dict] = None):
    EVENTS.append({
        "ts": dt.datetime.utcnow().isoformat(),
        "user_id": user_id,
        "source": source,
        "action": action,
        "payload": payload or {},
    })


async def add_lead(lead: dict) -> LeadRecord:
    async with session_scope() as session:
        user = None
        if lead.get("user_id"):
            user = await _load_user(session, int(lead["user_id"]))
            if user is None:
                user = User(telegram_id=int(lead["user_id"]), ref_code=str(lead["user_id"]))
                session.add(user)
                await session.flush()
        orm_lead = Lead(
            user=user,
            username=lead.get("username"),
            name=lead.get("name", ""),
            phone=lead.get("phone", ""),
            comment=lead.get("comment"),
            metadata=lead.get("metadata", {}),
        )
        session.add(orm_lead)
        await session.flush()
        await session.refresh(orm_lead, attribute_names=["user"])
        record = _map_lead(orm_lead)
    await log_admin_event(
        "lead_created",
        {
            "lead_id": record.id,
            "user_id": record.user_id,
            "name": record.name,
        },
    )
    return record


async def get_leads_last(n: int = 10) -> list[LeadRecord]:
    async with session_scope() as session:
        stmt = select(Lead).order_by(Lead.created_at.desc()).limit(n)
        result = await session.scalars(stmt.options(selectinload(Lead.user)))
        return [_map_lead(lead) for lead in result]


async def get_leads_all() -> list[LeadRecord]:
    async with session_scope() as session:
        stmt = select(Lead).order_by(Lead.created_at.desc())
        result = await session.scalars(stmt.options(selectinload(Lead.user)))
        return [_map_lead(lead) for lead in result]


async def count_users() -> int:
    async with session_scope() as session:
        result = await session.execute(select(func.count()).select_from(User))
        return int(result.scalar_one())


async def count_notify_enabled() -> int:
    async with session_scope() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(User.notify_enabled.is_(True))
        )
        return int(result.scalar_one())


async def count_leads() -> int:
    async with session_scope() as session:
        result = await session.execute(select(func.count()).select_from(Lead))
        return int(result.scalar_one())


async def get_notify_users() -> list[tuple[int, str]]:
    async with session_scope() as session:
        result = await session.execute(
            select(User.telegram_id, User.timezone).where(User.notify_enabled.is_(True))
        )
        return [(row[0], row[1]) for row in result]


async def upsert_product(code: str, name: str, *, description: str | None = None, price_label: str | None = None, metadata: dict | None = None) -> Product:
    async with session_scope() as session:
        stmt = select(Product).where(Product.code == code)
        product = await session.scalar(stmt)
        if product is None:
            product = Product(code=code, name=name)
            session.add(product)
            await session.flush()
        product.name = name
        product.description = description
        product.price_label = price_label
        product.meta = metadata or {}
        await session.flush()
        return product


async def set_subscription(
    user_tg_id: int,
    *,
    plan_code: str,
    expires_at: Optional[dt.datetime],
    external_id: Optional[str] = None,
    product_code: Optional[str] = None,
) -> SubscriptionInfo:
    async with session_scope() as session:
        user = await _load_user(session, user_tg_id)
        if user is None:
            user = User(telegram_id=user_tg_id, ref_code=str(user_tg_id))
            session.add(user)
            await session.flush()

        product = None
        if product_code:
            stmt = select(Product).where(Product.code == product_code)
            product = await session.scalar(stmt)

        sub = await _load_active_subscription(session, user.id)
        if sub is None:
            sub = Subscription(user=user)
            session.add(sub)
        sub.plan_code = plan_code
        sub.expires_at = expires_at
        sub.external_id = external_id
        sub.product = product
        sub.status = "active"
        sub.started_at = dt.datetime.now(dt.timezone.utc)
        await session.flush()
        return _map_subscription(sub)


async def update_subscription_expiry(user_tg_id: int, expires_at: Optional[dt.datetime]) -> Optional[SubscriptionInfo]:
    async with session_scope() as session:
        user = await _load_user(session, user_tg_id)
        if user is None:
            return None
        sub = await _load_active_subscription(session, user.id)
        if sub is None:
            return None
        sub.expires_at = expires_at
        await session.flush()
        return _map_subscription(sub)


async def clear_subscription(user_tg_id: int) -> None:
    await mutate_user(user_tg_id, lambda u: None)  # ensure user exists
    async with session_scope() as session:
        user = await _load_user(session, user_tg_id)
        if user is None:
            return
        sub = await _load_active_subscription(session, user.id)
        if sub is not None:
            sub.status = "cancelled"
            await session.flush()
