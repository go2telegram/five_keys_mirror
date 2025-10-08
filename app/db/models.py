from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
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
    referrals: Mapped[list["Referral"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Referral.user_id"
    )
    quiz_results: Mapped[list["QuizResult"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscriptions_user"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="subscription")


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


class QuizResult(Base):
    __tablename__ = "quiz_results"
    __table_args__ = (
        Index("ix_quiz_results_user", "user_id"),
        Index("ix_quiz_results_quiz", "quiz_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    quiz_name: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[dict] = mapped_column(_json_meta_type, nullable=False, default=dict)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="quiz_results")
