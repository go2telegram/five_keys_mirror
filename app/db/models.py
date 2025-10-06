from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    asked_notify: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ref_code: Mapped[str] = mapped_column(String(64), unique=True)
    ref_clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_joins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_conversions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ref_users: Mapped[list[int]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    last_plan: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    extra: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)

    referred_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    referred_by: Mapped[Optional["User"]] = relationship(remote_side="User.id", back_populates="referrals")

    referrals: Mapped[list["User"]] = relationship(back_populates="referred_by")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    metadata: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="product", cascade="all, delete-orphan")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    plan_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    product: Mapped[Optional["Product"]] = relationship(back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("user_id", "status", name="uq_subscription_active"),
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[Optional["User"]] = relationship(back_populates="leads")


class AdminEvent(Base):
    __tablename__ = "admin_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
