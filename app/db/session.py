from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from app.config import settings

DB_URL = getattr(settings, "DATABASE_URL", None) or "sqlite:///five_keys.sqlite3"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

def get_session():
    return SessionLocal()

def init_db():
    from app.db.models import Base
    Base.metadata.create_all(bind=engine)
