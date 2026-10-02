"""Engine/sesión SQLAlchemy + dependency `get_db` (síncrona por defecto)."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(get_settings().DATABASE_URL)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


SessionLocal = _build_session_factory()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
