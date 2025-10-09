from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


_json_meta_type = JSONB().with_variant(JSON(), "sqlite")
_bigint_pk = BigInteger().with_variant(Integer(), "sqlite")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_referred_by", "referred_by"),
    )

    id: Mapped[int] = mapped_column(_bigint_pk, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    referred_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    subscription: Mapped["Subscription"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    referrals: Mapped[list["Referral"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Referral.user_id"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscriptions_user"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="subscription")


class CommerceSubscription(Base):
    __tablename__ = "commerce_subscriptions"
    __table_args__ = (Index("ix_commerce_subscriptions_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    amount: Mapped[float] = mapped_column(Float(asdecimal=False), nullable=False, default=0.0)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_id", "user_id"),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    items_json: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
    amount: Mapped[float] = mapped_column(Float(asdecimal=False), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    coupon_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    utm_json: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Coupon(Base):
    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_or_pct: Mapped[float] = mapped_column(Float(asdecimal=False), nullable=False)
    valid_till: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    usage_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Bundle(Base):
    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    items_json: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
    price: Mapped[float] = mapped_column(Float(asdecimal=False), nullable=False)
    active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        Index("ix_ref_user", "user_id"),
        Index("ix_ref_invited", "invited_id"),
        Index("ix_ref_conv", "converted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invited_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bonus_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    user: Mapped[User] = relationship(back_populates="referrals", foreign_keys=[user_id])


class PromoUsage(Base):
    __tablename__ = "promo_usage"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_promo_usage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_user", "user_id"),
        Index("ix_events_name", "name"),
        Index("ix_events_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(_bigint_pk, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_ts", "ts"),)

    id: Mapped[int] = mapped_column(_bigint_pk, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TrackEvent(Base):
    __tablename__ = "track_events"
    __table_args__ = (
        Index("ix_track_events_user_kind_ts", "user_id", "kind", "ts"),
        Index("ix_track_events_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(_bigint_pk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Float(asdecimal=False), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    plan_json: Mapped[dict | None] = mapped_column(_json_meta_type, nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")


class RetentionPush(Base):
    __tablename__ = "retention_pushes"
    __table_args__ = (UniqueConstraint("user_id", "flow", name="uq_retention_push"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    flow: Mapped[str] = mapped_column(String(32), nullable=False)
    last_sent: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DailyTip(Base):
    __tablename__ = "daily_tips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RetentionSetting(Base):
    __tablename__ = "retention_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    tips_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tips_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(10, 0))
    last_tip_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_tip_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    water_window_start: Mapped[time] = mapped_column(Time, nullable=False, default=time(9, 0))
    water_window_end: Mapped[time] = mapped_column(Time, nullable=False, default=time(21, 0))
    water_last_sent_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    water_sent_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    water_goal_ml: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    water_reminders: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    weight_kg: Mapped[float | None] = mapped_column(Float(asdecimal=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RetentionJourney(Base):
    __tablename__ = "retention_journeys"
    __table_args__ = (Index("ix_retention_journeys_schedule", "journey", "scheduled_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    journey: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
