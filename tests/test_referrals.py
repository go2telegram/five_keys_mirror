from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Referral, User


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    return session_factory()


def test_referral_relationship_roundtrip() -> None:
    session = create_session()

    referrer = User(id=1, telegram_id=101, timezone="UTC")
    referred = User(id=2, telegram_id=202, timezone="UTC")
    session.add_all([referrer, referred])
    session.flush()

    referral = Referral(id=100, referrer_id=referrer.id, user_id=referred.id)
    session.add(referral)
    session.commit()

    fetched = session.execute(select(Referral).where(Referral.id == referral.id)).scalar_one()

    assert fetched.referrer.telegram_id == referrer.telegram_id
    assert fetched.user.telegram_id == referred.telegram_id
    assert referred.referred_by.referrer_id == referrer.id

    session.close()
