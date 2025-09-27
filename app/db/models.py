from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=True)
    created  = Column(DateTime, default=datetime.utcnow)
    subscription = relationship("Subscription", uselist=False, back_populates="user", cascade="all, delete-orphan")

class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    plan    = Column(String, nullable=False)
    since   = Column(DateTime, nullable=False)
    until   = Column(DateTime, nullable=False)
    user    = relationship("User", back_populates="subscription")

class Referral(Base):
    __tablename__ = "referrals"
    id          = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, index=True)
    invited_id  = Column(Integer, index=True, unique=True)
    joined_at   = Column(DateTime, default=datetime.utcnow)
    converted_at= Column(DateTime, nullable=True)
    bonus_days  = Column(Integer, default=0)

class PromoUsage(Base):
    __tablename__ = "promo_usages"
    id      = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    code    = Column(String, index=True)
    used_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_user_promo"),)

class Event(Base):
    __tablename__ = "events"
    id      = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    name    = Column(String, index=True)
    meta    = Column(String, nullable=True)
    ts      = Column(DateTime, default=datetime.utcnow, index=True)
