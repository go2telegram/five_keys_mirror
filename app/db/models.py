from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(length=255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(length=255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(length=255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(length=8), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(length=64), server_default="Europe/Moscow", nullable=False
    )

    referrals: Mapped[list["Referral"]] = relationship(
        back_populates="referrer",
        cascade="all, delete-orphan",
        foreign_keys="Referral.referrer_id",
    )
    referred_by: Mapped[Optional["Referral"]] = relationship(
        back_populates="user",
        foreign_keys="Referral.user_id",
        uselist=False,
    )


class Referral(TimestampMixin, Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_referrals_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    referrer: Mapped[User] = relationship(
        back_populates="referrals",
        foreign_keys=[referrer_id],
    )
    user: Mapped[User] = relationship(
        back_populates="referred_by",
        foreign_keys=[user_id],
    )
